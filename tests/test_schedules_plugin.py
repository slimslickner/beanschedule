"""Tests for schedules plugin (YAML-based forecast generation)."""

from datetime import date
from decimal import Decimal

import pytest
from beancount.core import amount, data

from beanschedule.plugins.schedules import schedules


@pytest.fixture
def sample_schedule_yaml(tmp_path):
    """Create a sample schedules directory."""
    schedules_dir = tmp_path / "schedules"
    schedules_dir.mkdir()
    (schedules_dir / "_config.yaml").write_text(
        """
default_currency: USD
forecast_months: 12
"""
    )
    (schedules_dir / "rent-monthly.yaml").write_text(
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
    return schedules_dir


@pytest.fixture
def disabled_schedule_yaml(tmp_path):
    """Create schedules directory with disabled schedule."""
    schedules_dir = tmp_path / "schedules"
    schedules_dir.mkdir()
    (schedules_dir / "disabled-schedule.yaml").write_text(
        """
id: disabled-schedule
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
    return schedules_dir


class TestSchedulesPlugin:
    """Tests for schedules plugin."""

    def test_plugin_generates_forecasts_from_yaml(self, sample_schedule_yaml):
        """Should generate forecast transactions from YAML schedules."""
        options_map = {"filename": str(sample_schedule_yaml.parent / "main.bean")}

        # Run plugin with explicit config file
        result_entries, errors = schedules(
            [], options_map, config=str(sample_schedule_yaml)
        )

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
        assert forecast_txn.postings[0].units == amount.Amount(
            Decimal("1500.00"), "USD"
        )
        assert forecast_txn.postings[1].account == "Assets:Checking"
        # Balancing posting should be calculated (negative of the first posting)
        assert forecast_txn.postings[1].units == amount.Amount(
            Decimal("-1500.00"), "USD"
        )

    def test_plugin_skips_disabled_schedules(self, disabled_schedule_yaml):
        """Should not generate forecasts for disabled schedules."""
        options_map = {"filename": str(disabled_schedule_yaml.parent / "main.bean")}

        result_entries, errors = schedules(
            [], options_map, config=str(disabled_schedule_yaml)
        )

        # Should not generate any forecasts
        assert len(result_entries) == 0, (
            "Should not generate forecasts for disabled schedules"
        )
        assert len(errors) == 0

    def test_plugin_handles_missing_yaml(self, tmp_path):
        """Should handle missing YAML file gracefully."""
        options_map = {"filename": str(tmp_path / "main.bean")}

        result_entries, errors = schedules(
            [], options_map, config=str(tmp_path / "nonexistent.yaml")
        )

        # Should return original entries unchanged
        assert len(result_entries) == 0
        # Should have error
        assert len(errors) > 0
        assert "not found" in errors[0].lower()

    def test_plugin_auto_discovers_schedules(self, sample_schedule_yaml, monkeypatch):
        """Should auto-discover schedules/ directory when no config_file provided."""
        from beanschedule import loader

        # Mock find_schedules_location to return our test directory
        monkeypatch.setattr(
            loader, "find_schedules_location", lambda: sample_schedule_yaml
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
            [existing_txn], options_map, config=str(sample_schedule_yaml)
        )

        # Should include existing entry + forecast entries
        assert len(result_entries) > 1
        assert existing_txn in result_entries
        assert len(errors) == 0

    def test_plugin_generates_multiple_months(self, sample_schedule_yaml):
        """Should generate forecasts for multiple months (12 months configured)."""
        options_map = {"filename": str(sample_schedule_yaml.parent / "main.bean")}

        result_entries, errors = schedules(
            [], options_map, config=str(sample_schedule_yaml)
        )

        # Should generate 12 months of forecasts (configured in fixture)
        forecast_txns = [e for e in result_entries if isinstance(e, data.Transaction)]
        assert len(forecast_txns) >= 12, "Should generate at least 12 monthly forecasts"

        # All should be on day 1 of month
        for txn in forecast_txns:
            assert txn.date.day == 1, "All forecasts should be on day 1"

    def test_plugin_with_bimonthly_schedule(self, tmp_path):
        """Should generate forecasts for bimonthly schedule (multiple days per month)."""
        schedule_dir = tmp_path / "schedules"
        schedule_dir.mkdir()
        (schedule_dir / "_config.yaml").write_text(
            """
forecast_months: 12
"""
        )
        (schedule_dir / "paycheck.yaml").write_text(
            """
id: paycheck
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
        result_entries, errors = schedules([], options_map, config=str(schedule_dir))

        # Should generate 2 forecasts per month (5th and 20th)
        forecast_txns = [e for e in result_entries if isinstance(e, data.Transaction)]
        assert len(forecast_txns) >= 24, (
            "Should generate at least 24 forecasts (2 per month)"
        )

        # Check days
        days = {txn.date.day for txn in forecast_txns}
        assert 5 in days
        assert 20 in days

    def test_plugin_with_posting_metadata(self, tmp_path):
        """Should include posting-level metadata in beancount postings."""
        schedule_dir = tmp_path / "schedules"
        schedule_dir.mkdir()
        (schedule_dir / "test.yaml").write_text(
            """
id: test
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
      metadata:
        narration: "Test expense note"
    - account: Assets:Checking
      metadata:
        narration: "Payment from checking"
"""
        )

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config=str(schedule_dir))

        # Check posting metadata
        forecast_txn = result_entries[0]
        assert forecast_txn.postings[0].meta is not None
        assert forecast_txn.postings[0].meta.get("narration") == "Test expense note"
        assert forecast_txn.postings[1].meta.get("narration") == "Payment from checking"

    def test_plugin_respects_forecast_months_config(self, tmp_path):
        """Should generate forecasts respecting forecast_months config."""
        schedule_dir = tmp_path / "schedules"
        schedule_dir.mkdir()
        # Set forecast_months to 1 to generate only 1 month ahead
        (schedule_dir / "_config.yaml").write_text(
            """
forecast_months: 1
"""
        )
        (schedule_dir / "test-monthly.yaml").write_text(
            """
id: test-monthly
enabled: true
match:
  account: Assets:Checking
  payee_pattern: "Test"
recurrence:
  frequency: MONTHLY
  start_date: 2024-01-01
  day_of_month: 1
transaction:
  payee: "Test Payment"
  narration: "Monthly test"
  metadata:
    schedule_id: test-monthly
  postings:
    - account: Expenses:Test
      amount: 100.00
    - account: Assets:Checking
"""
        )

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config=str(schedule_dir))

        assert len(errors) == 0
        forecasts = [
            e
            for e in result_entries
            if isinstance(e, data.Transaction) and e.flag == "#"
        ]
        # With forecast_months=1, should have fewer forecasts than default (3 months)
        assert len(forecasts) >= 1
        # All forecasts should be within 1 month (+ 1 day for tomorrow start)
        assert all(
            (e.date - date.today()).days <= 32
            for e in forecasts  # ~1 month
        )


class TestPluginErrorHandling:
    """Tests for plugin error handling."""

    def test_invalid_yaml_syntax(self, tmp_path):
        """Should handle invalid schedule YAML gracefully (skip and continue)."""
        schedule_dir = tmp_path / "schedules"
        schedule_dir.mkdir()
        (schedule_dir / "invalid-schedule.yaml").write_text(
            "invalid: yaml: syntax: here:"
        )

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config=str(schedule_dir))

        # Invalid schedule files are skipped gracefully
        assert len(errors) == 0

    def test_missing_required_fields(self, tmp_path):
        """Should handle missing required fields in schedule (skip file gracefully)."""
        schedule_dir = tmp_path / "schedules"
        schedule_dir.mkdir()
        (schedule_dir / "incomplete.yaml").write_text(
            """
id: incomplete
# Missing enabled, match, recurrence, transaction
"""
        )

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config=str(schedule_dir))

        # Invalid schedule files are skipped gracefully
        assert len(errors) == 0


class TestPluginWithLedgerFile:
    """Integration tests with actual ledger files."""

    def test_relative_path_resolution(self, tmp_path):
        """Should resolve relative config paths relative to ledger file."""
        # Create subdirectory structure
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        schedule_dir = config_dir / "schedules"
        schedule_dir.mkdir()
        (schedule_dir / "test.yaml").write_text(
            """
id: test
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
        result_entries, errors = schedules([], options_map, config="config/schedules")

        # Should resolve correctly and generate forecasts
        assert len(result_entries) > 0
        assert len(errors) == 0


class TestPluginFileMetadata:
    """Tests for filename metadata in forecast transactions."""

    def test_directory_schedule_sets_individual_filename(self, tmp_path, monkeypatch):
        """Should set filename metadata to individual schedule file in directory mode."""
        schedule_dir = tmp_path / "schedules"
        schedule_dir.mkdir()
        (schedule_dir / "test-schedule.yaml").write_text(
            """
id: test-schedule
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

        monkeypatch.chdir(tmp_path)

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config=str(schedule_dir))

        assert len(errors) == 0
        forecast_txn = result_entries[0]
        assert "filename" in forecast_txn.meta
        # Should show relative path to individual schedule file
        assert "test-schedule.yaml" in forecast_txn.meta["filename"]
        assert forecast_txn.meta["lineno"] == 0

    def test_directory_mode_sets_individual_filenames(self, tmp_path, monkeypatch):
        """Should set filename to individual schedule files in directory mode."""
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
        monkeypatch.setattr(loader, "find_schedules_location", lambda: schedules_dir)

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map)

        # Should have forecasts from both schedules
        assert len(result_entries) > 0
        assert len(errors) == 0

        # Check that different schedules have different source files
        rent_forecasts = [
            e for e in result_entries if e.meta.get("schedule_id") == "rent-monthly"
        ]
        paycheck_forecasts = [
            e for e in result_entries if e.meta.get("schedule_id") == "paycheck"
        ]

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

        # Create nested structure
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        schedule_dir = config_dir / "schedules"
        schedule_dir.mkdir()
        (schedule_dir / "test.yaml").write_text(
            """
id: test
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
        result_entries, errors = schedules([], options_map, config=str(schedule_dir))

        # Check filename metadata uses relative path from BEANSCHEDULE_DISPLAY_BASE
        assert len(errors) == 0
        forecast_txn = result_entries[0]
        # Should show path relative to BEANSCHEDULE_DISPLAY_BASE
        assert "config/schedules/test.yaml" in forecast_txn.meta["filename"]


class TestAmortizationRoleValidation:
    """Tests for explicit role validation on amortization schedules."""

    def test_missing_role_raises_helpful_error(self, tmp_path, monkeypatch):
        """Should raise helpful error when role is missing on amortization posting."""
        from beanschedule.plugins.schedules import schedules

        schedule_dir = tmp_path / "schedules"
        schedule_dir.mkdir()
        (schedule_dir / "mortgage-no-role.yaml").write_text(
            """
id: mortgage-no-role
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
        result_entries, errors = schedules([], options_map, config=str(schedule_dir))

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

        schedule_dir = tmp_path / "schedules"
        schedule_dir.mkdir()
        (schedule_dir / "mortgage-with-escrow.yaml").write_text(
            """
id: mortgage-with-escrow
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
        result_entries, errors = schedules([], options_map, config=str(schedule_dir))

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

        schedule_dir = tmp_path / "schedules"
        schedule_dir.mkdir()
        (schedule_dir / "test-mortgage.yaml").write_text(
            """
id: test-mortgage
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
        result_entries, errors = schedules([], options_map, config=str(schedule_dir))

        forecast_txn = result_entries[0]

        # Should have amortization metadata
        assert "amortization_payment_number" in forecast_txn.meta
        assert "amortization_balance_after" in forecast_txn.meta
        assert "amortization_principal" in forecast_txn.meta
        assert "amortization_interest" in forecast_txn.meta

        # Payment number will be based on forecast date (today + 1 year)
        # Just verify it's a positive integer
        assert forecast_txn.meta["amortization_payment_number"] > 0


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

    def _schedule_yaml(self, tmp_path, compounding="MONTHLY", extra_principal=None):
        """Build a schedules directory for the test loan and return the directory path."""
        schedule_dir = tmp_path / "schedules"
        if not schedule_dir.exists():
            schedule_dir.mkdir()

        config_lines = [
            "forecast_months: 12",
        ]
        (schedule_dir / "_config.yaml").write_text("\n".join(config_lines))

        schedule_lines = [
            "id: test-loan",
            "enabled: true",
            "match:",
            "  account: Assets:Checking",
            '  payee_pattern: "LOAN"',
            "recurrence:",
            "  frequency: MONTHLY",
            "  start_date: 2020-01-01",
            "  day_of_month: 4",
            "amortization:",
            "  annual_rate: 0.06",
            "  balance_from_ledger: true",
            "  monthly_payment: 200.00",
            f"  compounding: {compounding}",
        ]
        if extra_principal is not None:
            schedule_lines.append(f"  extra_principal: {extra_principal}")
        schedule_lines.extend(
            [
                "transaction:",
                '  payee: "Loan Payment"',
                '  narration: "Monthly loan payment"',
                "  metadata:",
                "    schedule_id: test-loan",
                "  postings:",
                "    - account: Assets:Checking",
                "      amount: null",
                "      role: payment",
                "    - account: Expenses:Interest",
                "      amount: null",
                "      role: interest",
                f"    - account: {self.LIABILITY_ACCOUNT}",
                "      amount: null",
                "      role: principal",
            ]
        )
        (schedule_dir / "test-loan.yaml").write_text("\n".join(schedule_lines))
        return schedule_dir

    # ── tests ─────────────────────────────────────────────────────────────

    def test_stateful_monthly_compounding(self, tmp_path, monkeypatch):
        """Should derive P/I from actual ledger balance, not original terms."""
        # Mock today to be before the first forecast date (2026-02-04)
        # so the test doesn't depend on the current date
        # We need to patch where date is actually used (in the schedules module)
        from datetime import date as dt_date

        mock_today_value = dt_date(2026, 1, 15)

        class MockDate:
            """Wrapper for date that allows mocking today()."""

            @staticmethod
            def today():
                return mock_today_value

            def __new__(cls, year, month, day):
                return dt_date(year, month, day)

        monkeypatch.setattr("beanschedule.plugins.schedules.date", MockDate)

        schedule_dir = self._schedule_yaml(tmp_path, "MONTHLY")
        monkeypatch.chdir(tmp_path)

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules(
            self._make_ledger_entries(), options_map, config=str(schedule_dir)
        )

        assert len(errors) == 0
        forecasts = [
            e
            for e in result_entries
            if isinstance(e, data.Transaction) and e.flag == "#"
        ]
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
        # Mock today to be before the first forecast date (2026-02-04)
        # so the test doesn't depend on the current date
        # We need to patch where date is actually used (in the schedules module)
        from datetime import date as dt_date

        mock_today_value = dt_date(2026, 1, 15)

        class MockDate:
            """Wrapper for date that allows mocking today()."""

            @staticmethod
            def today():
                return mock_today_value

            def __new__(cls, year, month, day):
                return dt_date(year, month, day)

        monkeypatch.setattr("beanschedule.plugins.schedules.date", MockDate)

        schedule_dir = self._schedule_yaml(tmp_path, "DAILY")
        monkeypatch.chdir(tmp_path)

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules(
            self._make_ledger_entries(), options_map, config=str(schedule_dir)
        )
        assert len(errors) == 0

        forecasts = [
            e
            for e in result_entries
            if isinstance(e, data.Transaction) and e.flag == "#"
        ]
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
        schedule_dir = self._schedule_yaml(tmp_path, "MONTHLY", extra_principal="50.00")
        monkeypatch.chdir(tmp_path)

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules(
            self._make_ledger_entries(), options_map, config=str(schedule_dir)
        )
        assert len(errors) == 0

        forecasts = [
            e
            for e in result_entries
            if isinstance(e, data.Transaction) and e.flag == "#"
        ]
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
                    amount.Amount(
                        Decimal("500.00"), "USD"
                    ),  # would lower balance if counted
                    None,
                    None,
                    None,
                    None,
                ),
            ],
        )

        schedule_dir = self._schedule_yaml(tmp_path, "MONTHLY")
        monkeypatch.chdir(tmp_path)

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules(
            self._make_ledger_entries(extra_entries=[phantom]),
            options_map,
            config=str(schedule_dir),
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

    def test_stateful_no_cleared_transactions_skips_schedule(
        self, tmp_path, monkeypatch
    ):
        """Schedule should be silently skipped when liability has no cleared postings."""
        schedule_dir = self._schedule_yaml(tmp_path, "MONTHLY")
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

        result_entries, errors = schedules(
            [phantom], options_map, config=str(schedule_dir)
        )
        # No hard errors — just a warning log and skip
        assert len(errors) == 0
        # No new forecasts generated for this schedule
        new_forecasts = [
            e
            for e in result_entries
            if isinstance(e, data.Transaction)
            and e.meta.get("schedule_id") == "test-loan"
        ]
        assert len(new_forecasts) == 0


class TestShadowAccountForecasting:
    """Tests for shadow_upcoming_account redirecting matched postings via plugin directive."""

    SHADOW_ACCOUNT = "Equity:Schedules:Upcoming"

    def _make_yaml(self, tmp_path):
        """Write a simple monthly schedule (directory mode, no shadow config)."""
        schedule_dir = tmp_path / "schedules"
        schedule_dir.mkdir()
        (schedule_dir / "rent-monthly.yaml").write_text(
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
  payee: "Rent Payment"
  narration: "Monthly rent"
  metadata:
    schedule_id: rent-monthly
  postings:
    - account: Expenses:Housing:Rent
      amount: 1500.00
    - account: Assets:Checking
"""
        )
        return schedule_dir

    def test_shadow_account_disabled_by_default(self, tmp_path):
        """Without shadow config in directive, forecast postings use the real matched account."""
        schedule_dir = self._make_yaml(tmp_path)
        options_map = {"filename": str(tmp_path / "main.bean")}

        result_entries, errors = schedules([], options_map, config=str(schedule_dir))

        assert len(errors) == 0
        forecast_txn = result_entries[0]
        accounts = [p.account for p in forecast_txn.postings]
        assert "Assets:Checking" in accounts
        assert self.SHADOW_ACCOUNT not in accounts

    def test_shadow_account_redirects_matched_posting(self, tmp_path):
        """shadow_upcoming_account passed to _create_forecast_transaction redirects the matched posting."""
        from datetime import date, timedelta

        from dateutil.relativedelta import relativedelta

        from beanschedule.loader import load_schedules_from_directory
        from beanschedule.plugins.schedules import _create_forecast_transaction
        from beanschedule.recurrence import RecurrenceEngine
        from beanschedule.utils import generate_schedule_occurrences

        schedule_dir = self._make_yaml(tmp_path)
        sf = load_schedules_from_directory(schedule_dir)
        assert sf is not None
        engine = RecurrenceEngine()
        today = date.today()
        start = today + timedelta(days=1)
        end = today + relativedelta(months=1)

        schedule = sf.schedules[0]
        occurrences = generate_schedule_occurrences(schedule, engine, start, end)
        assert len(occurrences) > 0

        txn = _create_forecast_transaction(
            schedule,
            occurrences[0],
            sf.config,
            shadow_account=self.SHADOW_ACCOUNT,
        )
        accounts = [p.account for p in txn.postings]
        assert "Assets:Checking" not in accounts
        assert self.SHADOW_ACCOUNT in accounts

    def test_shadow_account_preserves_non_matched_postings(self, tmp_path):
        """Expense/income postings are left untouched when shadow account is configured."""
        from datetime import date, timedelta

        from dateutil.relativedelta import relativedelta

        from beanschedule.loader import load_schedules_from_directory
        from beanschedule.plugins.schedules import _create_forecast_transaction
        from beanschedule.recurrence import RecurrenceEngine
        from beanschedule.utils import generate_schedule_occurrences

        schedule_dir = self._make_yaml(tmp_path)
        sf = load_schedules_from_directory(schedule_dir)
        assert sf is not None
        engine = RecurrenceEngine()
        today = date.today()
        start = today + timedelta(days=1)
        end = today + relativedelta(months=1)

        schedule = sf.schedules[0]
        occurrences = generate_schedule_occurrences(schedule, engine, start, end)

        txn = _create_forecast_transaction(
            schedule,
            occurrences[0],
            sf.config,
            shadow_account=self.SHADOW_ACCOUNT,
        )
        accounts = [p.account for p in txn.postings]
        assert "Expenses:Housing:Rent" in accounts

    def test_shadow_account_preserves_amounts(self, tmp_path):
        """Redirected posting keeps its amount unchanged."""
        from datetime import date, timedelta

        from dateutil.relativedelta import relativedelta

        from beanschedule.loader import load_schedules_from_directory
        from beanschedule.plugins.schedules import _create_forecast_transaction
        from beanschedule.recurrence import RecurrenceEngine
        from beanschedule.utils import generate_schedule_occurrences

        schedule_dir = self._make_yaml(tmp_path)
        sf = load_schedules_from_directory(schedule_dir)
        assert sf is not None
        engine = RecurrenceEngine()
        today = date.today()
        start = today + timedelta(days=1)
        end = today + relativedelta(months=1)

        schedule = sf.schedules[0]
        occurrences = generate_schedule_occurrences(schedule, engine, start, end)

        txn = _create_forecast_transaction(
            schedule,
            occurrences[0],
            sf.config,
            shadow_account=self.SHADOW_ACCOUNT,
        )
        postings_by_account = {p.account: p.units for p in txn.postings}
        shadow_posting = postings_by_account[self.SHADOW_ACCOUNT]
        assert shadow_posting == amount.Amount(Decimal("-1500.00"), "USD")

    def test_shadow_account_via_plugin_directive(self, tmp_path, monkeypatch):
        """shadow_upcoming_account passed via plugin directive dict is applied to all forecasts."""
        from beanschedule import loader

        schedule_dir = self._make_yaml(tmp_path)
        monkeypatch.setattr(loader, "find_schedules_location", lambda: schedule_dir)
        options_map = {"filename": str(tmp_path / "main.bean")}

        result_entries, errors = schedules(
            [],
            options_map,
            config={
                "forecast_months": 1,
                "shadow_upcoming_account": self.SHADOW_ACCOUNT,
            },
        )

        assert len(errors) == 0
        txns = [e for e in result_entries if isinstance(e, data.Transaction)]
        assert len(txns) > 0
        for txn in txns:
            accounts = [p.account for p in txn.postings]
            assert "Assets:Checking" not in accounts
            assert self.SHADOW_ACCOUNT in accounts

    def test_shadow_account_open_directive_generated(self, tmp_path, monkeypatch):
        """An Open directive is automatically added for the shadow account."""
        from beanschedule import loader

        schedule_dir = self._make_yaml(tmp_path)
        monkeypatch.setattr(loader, "find_schedules_location", lambda: schedule_dir)
        options_map = {"filename": str(tmp_path / "main.bean")}

        result_entries, errors = schedules(
            [],
            options_map,
            config={
                "forecast_months": 1,
                "shadow_upcoming_account": self.SHADOW_ACCOUNT,
            },
        )

        assert len(errors) == 0
        open_directives = [e for e in result_entries if isinstance(e, data.Open)]
        opened_accounts = {o.account for o in open_directives}
        assert self.SHADOW_ACCOUNT in opened_accounts

    def test_open_directive_not_duplicated_when_already_open(
        self, tmp_path, monkeypatch
    ):
        """No duplicate Open directive is added if the account is already open in the ledger."""
        from beanschedule import loader

        schedule_dir = self._make_yaml(tmp_path)
        monkeypatch.setattr(loader, "find_schedules_location", lambda: schedule_dir)
        options_map = {"filename": str(tmp_path / "main.bean")}

        existing_open = data.Open(
            {"filename": "main.bean", "lineno": 1},
            date(2024, 1, 1),
            self.SHADOW_ACCOUNT,
            None,  # type: ignore[arg-type]
            None,
        )

        result_entries, errors = schedules(
            [existing_open],
            options_map,
            config={
                "forecast_months": 1,
                "shadow_upcoming_account": self.SHADOW_ACCOUNT,
            },
        )

        assert len(errors) == 0
        open_directives = [
            e
            for e in result_entries
            if isinstance(e, data.Open) and e.account == self.SHADOW_ACCOUNT
        ]
        assert len(open_directives) == 1, "Should not create a duplicate Open directive"


class TestShadowOverdueForecasting:
    """Tests for shadow_overdue_account generating past-due plugin transactions."""

    OVERDUE_ACCOUNT = "Equity:Schedules:Overdue"
    UPCOMING_ACCOUNT = "Equity:Schedules:Upcoming"

    def _make_yaml(self, tmp_path):
        """Write a schedule that has been recurring since well before today."""
        schedule_dir = tmp_path / "schedules"
        schedule_dir.mkdir()
        (schedule_dir / "rent-monthly.yaml").write_text(
            """
id: rent-monthly
enabled: true
match:
  account: Assets:Checking
  payee_pattern: ".*LANDLORD.*"
recurrence:
  frequency: MONTHLY
  start_date: 2020-01-01
  day_of_month: 1
transaction:
  payee: "Rent Payment"
  narration: "Monthly rent"
  metadata:
    schedule_id: rent-monthly
  postings:
    - account: Expenses:Housing:Rent
      amount: 1500.00
    - account: Assets:Checking
"""
        )
        return schedule_dir

    def test_overdue_transactions_not_generated_by_default(self, tmp_path, monkeypatch):
        """Without shadow_overdue_account, plugin starts from tomorrow — no past dates."""
        from beanschedule import loader

        schedule_dir = self._make_yaml(tmp_path)
        monkeypatch.setattr(loader, "find_schedules_location", lambda: schedule_dir)
        options_map = {"filename": str(tmp_path / "main.bean")}

        result_entries, errors = schedules(
            [], options_map, config={"forecast_months": 1}
        )

        assert len(errors) == 0
        today = date.today()
        for txn in result_entries:
            assert txn.date > today, "No past-dated transactions without overdue config"

    def test_overdue_generates_past_transactions(self, tmp_path, monkeypatch):
        """With shadow_overdue_account, past-due occurrences are generated."""
        from beanschedule import loader

        schedule_dir = self._make_yaml(tmp_path)
        monkeypatch.setattr(loader, "find_schedules_location", lambda: schedule_dir)
        options_map = {"filename": str(tmp_path / "main.bean")}

        result_entries, errors = schedules(
            [],
            options_map,
            config={
                "forecast_months": 1,
                "shadow_overdue_account": self.OVERDUE_ACCOUNT,
            },
        )

        assert len(errors) == 0
        today = date.today()
        past_txns = [e for e in result_entries if e.date <= today]
        assert len(past_txns) > 0, "Should generate past-dated transactions"

    def test_overdue_posts_to_overdue_account(self, tmp_path, monkeypatch):
        """Past-due transactions use shadow_overdue_account, not the real account."""
        from beanschedule import loader

        schedule_dir = self._make_yaml(tmp_path)
        monkeypatch.setattr(loader, "find_schedules_location", lambda: schedule_dir)
        options_map = {"filename": str(tmp_path / "main.bean")}

        result_entries, errors = schedules(
            [],
            options_map,
            config={
                "forecast_months": 1,
                "shadow_overdue_account": self.OVERDUE_ACCOUNT,
            },
        )

        assert len(errors) == 0
        today = date.today()
        past_txns = [
            e
            for e in result_entries
            if isinstance(e, data.Transaction) and e.date <= today
        ]
        assert len(past_txns) > 0
        for txn in past_txns:
            accounts = [p.account for p in txn.postings]
            assert "Assets:Checking" not in accounts
            assert self.OVERDUE_ACCOUNT in accounts

    def test_upcoming_posts_to_upcoming_account(self, tmp_path, monkeypatch):
        """Future transactions use shadow_upcoming_account when both are configured."""
        from beanschedule import loader

        schedule_dir = self._make_yaml(tmp_path)
        monkeypatch.setattr(loader, "find_schedules_location", lambda: schedule_dir)
        options_map = {"filename": str(tmp_path / "main.bean")}

        result_entries, errors = schedules(
            [],
            options_map,
            config={
                "forecast_months": 1,
                "shadow_overdue_account": self.OVERDUE_ACCOUNT,
                "shadow_upcoming_account": self.UPCOMING_ACCOUNT,
            },
        )

        assert len(errors) == 0
        today = date.today()
        txns = [e for e in result_entries if isinstance(e, data.Transaction)]
        for txn in txns:
            accounts = [p.account for p in txn.postings]
            assert "Assets:Checking" not in accounts
            if txn.date <= today:
                assert self.OVERDUE_ACCOUNT in accounts
                assert self.UPCOMING_ACCOUNT not in accounts
            else:
                assert self.UPCOMING_ACCOUNT in accounts
                assert self.OVERDUE_ACCOUNT not in accounts

    def test_overdue_filtered_when_actual_transaction_exists(
        self, tmp_path, monkeypatch
    ):
        """Past dates with real imported transactions are not duplicated as overdue."""
        from beanschedule import loader
        from beancount.core import amount, data
        from decimal import Decimal
        from datetime import date as dt_date
        from dateutil.relativedelta import relativedelta

        schedule_dir = self._make_yaml(tmp_path)
        monkeypatch.setattr(loader, "find_schedules_location", lambda: schedule_dir)
        options_map = {"filename": str(tmp_path / "main.bean")}

        # Create a real imported transaction for last month's rent
        today = dt_date.today()
        last_month_first = (today - relativedelta(months=1)).replace(day=1)
        existing_txn = data.Transaction(
            meta={"filename": "main.bean", "lineno": 1, "schedule_id": "rent-monthly"},
            date=last_month_first,
            flag="*",
            payee="Rent Payment",
            narration="Monthly rent",
            tags=frozenset(),
            links=frozenset(),
            postings=[
                data.Posting(
                    "Expenses:Housing:Rent",
                    amount.Amount(Decimal("1500.00"), "USD"),
                    None,
                    None,
                    None,
                    None,
                ),
                data.Posting(
                    "Assets:Checking",
                    amount.Amount(Decimal("-1500.00"), "USD"),
                    None,
                    None,
                    None,
                    None,
                ),
            ],
        )

        result_entries, errors = schedules(
            [existing_txn],
            options_map,
            config={
                "forecast_months": 0,
                "shadow_overdue_account": self.OVERDUE_ACCOUNT,
            },
        )

        assert len(errors) == 0
        # The date with an existing transaction should not appear in overdue
        overdue_txns = [
            e
            for e in result_entries
            if isinstance(e, data.Transaction)
            and e.date == last_month_first
            and e.flag == "#"
        ]
        assert len(overdue_txns) == 0, (
            "Should not generate overdue for already-matched dates"
        )

    def test_overdue_filtered_when_transaction_posted_within_date_window(
        self, tmp_path, monkeypatch
    ):
        """Existing transaction posted within date_window days of expected date suppresses forecast.

        Regression test: previously the filter used exact date matching, so a transaction
        posted on the 3rd (expected the 1st) would not be filtered, causing a duplicate
        overdue forecast for the 1st.
        """
        from beanschedule import loader
        from beancount.core import amount, data
        from decimal import Decimal
        from datetime import date as dt_date
        from dateutil.relativedelta import relativedelta

        schedule_dir = self._make_yaml(tmp_path)
        monkeypatch.setattr(loader, "find_schedules_location", lambda: schedule_dir)
        options_map = {"filename": str(tmp_path / "main.bean")}

        today = dt_date.today()
        # Expected occurrence: 1st of last month
        last_month_first = (today - relativedelta(months=1)).replace(day=1)
        # Actual posting: 2 days later (within default 3-day window)
        actual_posting_date = last_month_first + relativedelta(days=2)

        existing_txn = data.Transaction(
            meta={
                "filename": "main.bean",
                "lineno": 1,
                "schedule_id": "rent-monthly",
            },
            date=actual_posting_date,  # Posted on the 3rd, expected on the 1st
            flag="*",
            payee="Rent Payment",
            narration="Monthly rent",
            tags=frozenset(),
            links=frozenset(),
            postings=[
                data.Posting(
                    "Expenses:Housing:Rent",
                    amount.Amount(Decimal("1500.00"), "USD"),
                    None,
                    None,
                    None,
                    None,
                ),
                data.Posting(
                    "Assets:Checking",
                    amount.Amount(Decimal("-1500.00"), "USD"),
                    None,
                    None,
                    None,
                    None,
                ),
            ],
        )

        result_entries, errors = schedules(
            [existing_txn],
            options_map,
            config={
                "forecast_months": 0,
                "shadow_overdue_account": self.OVERDUE_ACCOUNT,
            },
        )

        assert len(errors) == 0
        # Neither the expected date (1st) nor the actual posting date (3rd) should
        # appear as a duplicate overdue forecast
        overdue_txns_for_month = [
            e
            for e in result_entries
            if isinstance(e, data.Transaction)
            and e.date.year == last_month_first.year
            and e.date.month == last_month_first.month
            and e.flag == "#"
        ]
        assert len(overdue_txns_for_month) == 0, (
            "Should not generate overdue when existing transaction is within date_window"
        )

    def test_overdue_not_generated_when_schedule_matched_date_outside_window(
        self, tmp_path, monkeypatch
    ):
        """Regression: posting date outside window but schedule_matched_date matches.

        When the bank posts a transaction several days after the scheduled date
        (e.g., expected 2026-02-28, posted 2026-03-04 — 4 days apart, outside a 3-day
        window), the hook enriches the transaction with schedule_matched_date=2026-02-28.
        The plugin must use that metadata as the anchor so it does not generate a
        duplicate overdue forecast for 2026-02-28.
        """
        from beanschedule import loader
        from beancount.core import amount, data
        from decimal import Decimal
        from datetime import date as dt_date
        from dateutil.relativedelta import relativedelta

        schedule_dir = self._make_yaml(tmp_path)
        monkeypatch.setattr(loader, "find_schedules_location", lambda: schedule_dir)
        options_map = {"filename": str(tmp_path / "main.bean")}

        today = dt_date.today()
        # Expected occurrence: 1st of last month
        last_month_first = (today - relativedelta(months=1)).replace(day=1)
        # Actual posting: 5 days later — *outside* the default 3-day window
        actual_posting_date = last_month_first + relativedelta(days=5)

        existing_txn = data.Transaction(
            meta={
                "filename": "main.bean",
                "lineno": 1,
                "schedule_id": "rent-monthly",
                # Authoritative expected date recorded by the hook at enrich time
                "schedule_matched_date": last_month_first.isoformat(),
            },
            date=actual_posting_date,
            flag="*",
            payee="Rent Payment",
            narration="Monthly rent",
            tags=frozenset(),
            links=frozenset(),
            postings=[
                data.Posting(
                    "Expenses:Housing:Rent",
                    amount.Amount(Decimal("1500.00"), "USD"),
                    None,
                    None,
                    None,
                    None,
                ),
                data.Posting(
                    "Assets:Checking",
                    amount.Amount(Decimal("-1500.00"), "USD"),
                    None,
                    None,
                    None,
                    None,
                ),
            ],
        )

        result_entries, errors = schedules(
            [existing_txn],
            options_map,
            config={
                "forecast_months": 0,
                "shadow_overdue_account": self.OVERDUE_ACCOUNT,
            },
        )

        assert len(errors) == 0
        overdue_txns_for_month = [
            e
            for e in result_entries
            if isinstance(e, data.Transaction)
            and e.date.year == last_month_first.year
            and e.date.month == last_month_first.month
            and e.flag == "#"
        ]
        assert len(overdue_txns_for_month) == 0, (
            "Should not generate overdue when schedule_matched_date covers the expected date, "
            "even if the actual posting date is outside the date window"
        )
