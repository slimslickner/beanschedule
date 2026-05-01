"""Tests for CLI commands."""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from beanschedule.cli import main

_EXAMPLES_SCHEDULES_DIR = Path(__file__).parent.parent / "examples" / "schedules"
_EXAMPLE_SCHEDULE_NAMES = ["rent-payment", "paycheck-biweekly", "credit-card-payment"]


@pytest.fixture
def cli_runner():
    """Create a Click test runner."""
    return CliRunner()


@pytest.fixture
def schedules_directory(tmp_path):
    """Create a temporary schedules directory from example schedules."""
    schedules_dir = tmp_path / "schedules"
    schedules_dir.mkdir()
    shutil.copy(
        _EXAMPLES_SCHEDULES_DIR / "_config.yaml", schedules_dir / "_config.yaml"
    )
    for name in _EXAMPLE_SCHEDULE_NAMES:
        shutil.copy(
            _EXAMPLES_SCHEDULES_DIR / f"{name}.yaml",
            schedules_dir / f"{name}.yaml",
        )
    return schedules_dir


class TestValidateCommand:
    """Tests for the validate command."""

    def test_validate_directory_success(self, cli_runner, schedules_directory):
        """Test validating a schedules directory successfully."""
        result = cli_runner.invoke(main, ["validate", str(schedules_directory)])
        assert result.exit_code == 0
        assert "Validation successful" in result.output
        assert "Total schedules: 3" in result.output
        assert "Enabled: 2" in result.output
        assert "Disabled: 1" in result.output

    def test_validate_file_not_found(self, cli_runner):
        """Test validating a non-existent file."""
        result = cli_runner.invoke(main, ["validate", "/nonexistent/path.yaml"])
        assert result.exit_code != 0

    def test_validate_invalid_yaml(self, cli_runner, tmp_path):
        """Test validating a file with invalid YAML syntax."""
        bad_file = tmp_path / "bad.yaml"
        with open(bad_file, "w") as f:
            f.write("invalid: yaml: content:")

        result = cli_runner.invoke(main, ["validate", str(bad_file)])
        assert result.exit_code == 1
        assert "Validation failed" in result.output

    def test_validate_empty_directory(self, cli_runner, tmp_path):
        """Test validating an empty schedules directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = cli_runner.invoke(main, ["validate", str(empty_dir)])
        assert result.exit_code == 0
        assert "Total schedules: 0" in result.output

    def test_validate_with_verbose_flag(self, cli_runner, schedules_directory):
        """Test validate command with verbose flag."""
        result = cli_runner.invoke(main, ["-v", "validate", str(schedules_directory)])
        assert result.exit_code == 0
        assert "Validation successful" in result.output


class TestListCommand:
    """Tests for the list command."""

    def test_list_table_format(self, cli_runner, schedules_directory):
        """Test listing schedules in table format."""
        result = cli_runner.invoke(main, ["list", str(schedules_directory)])
        assert result.exit_code == 0
        assert "ID" in result.output
        assert "Status" in result.output
        assert "rent-payment" in result.output
        assert "paycheck-biweekly" in result.output
        assert "credit-card-payment" in result.output
        assert "Total: 3 schedules" in result.output

    def test_list_directory_table_format(self, cli_runner, schedules_directory):
        """Test listing schedules from directory in table format."""
        result = cli_runner.invoke(main, ["list", str(schedules_directory)])
        assert result.exit_code == 0
        assert "rent-payment" in result.output
        assert "Total: 3 schedules" in result.output

    def test_list_enabled_only_filter(self, cli_runner, schedules_directory):
        """Test listing only enabled schedules."""
        result = cli_runner.invoke(
            main, ["list", str(schedules_directory), "--enabled-only"]
        )
        assert result.exit_code == 0
        assert "rent-payment" in result.output
        assert "paycheck-biweekly" in result.output
        assert "credit-card-payment" not in result.output
        assert "Total: 2 schedules" in result.output

    def test_list_json_format(self, cli_runner, schedules_directory):
        """Test listing schedules in JSON format."""
        result = cli_runner.invoke(
            main, ["list", str(schedules_directory), "--format", "json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 3
        ids = [d["id"] for d in data]
        assert "rent-payment" in ids

    def test_list_csv_format(self, cli_runner, schedules_directory):
        """Test listing schedules in CSV format."""
        result = cli_runner.invoke(
            main, ["list", str(schedules_directory), "--format", "csv"]
        )
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert lines[0] == "ID,Enabled,RRULE,Payee,Account,Amount"
        assert "rent-payment" in result.output

    def test_list_csv_enabled_only(self, cli_runner, schedules_directory):
        """Test listing enabled schedules in CSV format."""
        result = cli_runner.invoke(
            main,
            [
                "list",
                str(schedules_directory),
                "--format",
                "csv",
                "--enabled-only",
            ],
        )
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 3  # Header + 2 enabled schedules

    def test_list_empty_directory(self, cli_runner, tmp_path):
        """Test listing from an empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = cli_runner.invoke(main, ["list", str(empty_dir)])
        assert result.exit_code == 0
        assert "No schedules found" in result.output

    def test_list_invalid_format(self, cli_runner, schedules_directory):
        """Test list command with invalid format."""
        result = cli_runner.invoke(
            main, ["list", str(schedules_directory), "--format", "invalid"]
        )
        assert result.exit_code != 0


class TestGenerateCommand:
    """Tests for the generate command."""

    def test_generate_monthly_schedule(self, cli_runner, schedules_directory):
        """Test generating occurrences for a monthly schedule."""
        result = cli_runner.invoke(
            main,
            [
                "generate",
                "rent-payment",
                "2024-01-01",
                "2024-03-31",
                "--schedules-path",
                str(schedules_directory),
            ],
        )
        if result.exit_code != 0:
            print(f"Error output: {result.output}")
            if result.exception:
                print(f"Exception: {result.exception}")
                import traceback

                traceback.print_exception(
                    type(result.exception),
                    result.exception,
                    result.exception.__traceback__,
                )
        assert result.exit_code == 0
        assert "Schedule: rent-payment" in result.output
        assert "RRULE:" in result.output
        assert "2024-01-06" in result.output
        assert "2024-02-06" in result.output
        assert "2024-03-06" in result.output
        assert "Expected occurrences (3)" in result.output

    def test_generate_weekly_schedule(self, cli_runner, schedules_directory):
        """Test generating occurrences for a weekly schedule."""
        result = cli_runner.invoke(
            main,
            [
                "generate",
                "paycheck-biweekly",
                "2024-01-01",
                "2024-02-29",
                "--schedules-path",
                str(schedules_directory),
            ],
        )
        assert result.exit_code == 0
        assert "Schedule: paycheck-biweekly" in result.output
        assert "RRULE:" in result.output
        # Should have some occurrences
        assert "Expected occurrences" in result.output

    def test_generate_schedule_not_found(self, cli_runner, schedules_directory):
        """Test generating for a non-existent schedule."""
        result = cli_runner.invoke(
            main,
            [
                "generate",
                "nonexistent",
                "2024-01-01",
                "2024-12-31",
                "--schedules-path",
                str(schedules_directory),
            ],
        )
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_generate_from_directory(self, cli_runner, schedules_directory):
        """Test generating from a schedules directory."""
        result = cli_runner.invoke(
            main,
            [
                "generate",
                "rent-payment",
                "2024-01-01",
                "2024-03-31",
                "--schedules-path",
                str(schedules_directory),
            ],
        )
        assert result.exit_code == 0
        assert "Schedule: rent-payment" in result.output
        assert "Expected occurrences (3)" in result.output


class TestInitCommand:
    """Tests for the init command."""

    def test_init_default_path(self, cli_runner, tmp_path):
        """Test init command with default path."""
        # We need to test this in a way that doesn't require changing directory
        output_dir = tmp_path / "schedules"

        result = cli_runner.invoke(
            main,
            ["init", str(output_dir)],
        )
        assert result.exit_code == 0
        assert "Initialized schedule directory" in result.output
        assert output_dir.exists()

    def test_init_creates_config(self, cli_runner, tmp_path):
        """Test that init creates the config file."""
        output_dir = tmp_path / "schedules"

        result = cli_runner.invoke(
            main,
            ["init", str(output_dir)],
        )
        assert result.exit_code == 0

        config_file = output_dir / "_config.yaml"
        assert config_file.exists()

        with open(config_file) as f:
            content = f.read()

        assert "fuzzy_match_threshold" in content
        assert "0.80" in content

    def test_init_creates_example_schedule(self, cli_runner, tmp_path):
        """Test that init creates an example schedule file."""
        output_dir = tmp_path / "schedules"

        result = cli_runner.invoke(
            main,
            ["init", str(output_dir)],
        )
        assert result.exit_code == 0

        example_file = output_dir / "example-rent.yaml"
        assert example_file.exists()

        with open(example_file) as f:
            example_data = yaml.safe_load(f)

        assert example_data["id"] == "example-rent"
        assert example_data["enabled"] is True

    def test_init_existing_directory_abort(self, cli_runner, tmp_path):
        """Test init aborts when directory exists without confirmation."""
        output_dir = tmp_path / "schedules"
        output_dir.mkdir()

        result = cli_runner.invoke(
            main,
            ["init", str(output_dir)],
            input="n",  # Abort the confirmation
        )
        assert result.exit_code != 0

    def test_init_existing_directory_confirm(self, cli_runner, tmp_path):
        """Test init succeeds when directory exists and user confirms."""
        output_dir = tmp_path / "schedules"
        output_dir.mkdir()

        # Create an old file to verify it gets overwritten
        old_file = output_dir / "old.txt"
        with open(old_file, "w") as f:
            f.write("old content")

        result = cli_runner.invoke(
            main,
            ["init", str(output_dir)],
            input="y",  # Confirm overwrite
        )
        assert result.exit_code == 0

        # Check that example file was created
        assert (output_dir / "example-rent.yaml").exists()

    def test_init_next_steps_shown(self, cli_runner, tmp_path):
        """Test that init shows next steps."""
        output_dir = tmp_path / "schedules"

        result = cli_runner.invoke(
            main,
            ["init", str(output_dir)],
        )
        assert result.exit_code == 0
        assert "Next steps" in result.output
        assert "Edit the example schedule file" in result.output
        assert "Validate your schedules" in result.output
        assert "Integrate with beangulp" in result.output


class TestMigrateCommand:
    """Tests for the migrate command."""

    _OLD_YAML = """\
id: old-schedule
enabled: true
match:
  account: Assets:Checking
  payee_pattern: "Test"
  amount: -100.00
  amount_tolerance: 5.00
  date_window_days: 3
recurrence:
  frequency: MONTHLY
  start_date: 2024-01-15
  end_date: null
  day_of_month: 15
  month: null
  day_of_week: null
  interval: 1
  days_of_month: null
  interval_months: null
transaction:
  payee: Test
  narration: Test payment
  metadata:
    schedule_id: old-schedule
missing_transaction:
  create_placeholder: true
  flag: '!'
  narration_prefix: '[MISSING]'
"""

    def test_migrate_rewrites_legacy_file(self, cli_runner, tmp_path):
        """Migrate rewrites old-format recurrence to rrule."""
        f = tmp_path / "old-schedule.yaml"
        f.write_text(self._OLD_YAML)

        result = cli_runner.invoke(main, ["migrate", str(tmp_path)])
        assert result.exit_code == 0
        assert "Migrated: old-schedule.yaml" in result.output
        assert "FREQ=MONTHLY;BYMONTHDAY=15" in result.output

        new_content = f.read_text()
        assert "rrule: FREQ=MONTHLY;BYMONTHDAY=15" in new_content
        assert "frequency:" not in new_content

    def test_migrate_dry_run(self, cli_runner, tmp_path):
        """Dry run shows changes without writing."""
        f = tmp_path / "old-schedule.yaml"
        f.write_text(self._OLD_YAML)
        original = f.read_text()

        result = cli_runner.invoke(main, ["migrate", "--dry-run", str(tmp_path)])
        assert result.exit_code == 0
        assert "Would migrate: old-schedule.yaml" in result.output
        assert f.read_text() == original  # unchanged

    def test_migrate_skips_new_format(self, cli_runner, tmp_path):
        """Files already using rrule format are skipped."""
        new_yaml = """\
id: new-schedule
enabled: true
match:
  account: Assets:Checking
  payee_pattern: "Test"
  amount: -100.00
  date_window_days: 3
recurrence:
  rrule: FREQ=MONTHLY;BYMONTHDAY=15
  start_date: 2024-01-15
transaction:
  payee: Test
  narration: Test
  metadata:
    schedule_id: new-schedule
missing_transaction:
  create_placeholder: true
  flag: '!'
  narration_prefix: '[MISSING]'
"""
        f = tmp_path / "new-schedule.yaml"
        f.write_text(new_yaml)

        result = cli_runner.invoke(main, ["migrate", str(tmp_path)])
        assert result.exit_code == 0
        assert "0 file(s) migrated" in result.output

    def test_migrate_weekly_biweekly(self, cli_runner, tmp_path):
        """Weekly biweekly schedule migrates correctly."""
        weekly_yaml = """\
id: paycheck
enabled: true
match:
  account: Assets:Checking
  payee_pattern: "Employer"
  amount: 1000.00
  date_window_days: 3
recurrence:
  frequency: WEEKLY
  start_date: 2024-01-05
  end_date: null
  day_of_month: null
  day_of_week: FRI
  interval: 2
  days_of_month: null
  interval_months: null
transaction:
  payee: Employer
  narration: Paycheck
  metadata:
    schedule_id: paycheck
missing_transaction:
  create_placeholder: true
  flag: '!'
  narration_prefix: '[MISSING]'
"""
        f = tmp_path / "paycheck.yaml"
        f.write_text(weekly_yaml)

        result = cli_runner.invoke(main, ["migrate", str(tmp_path)])
        assert result.exit_code == 0
        assert "FREQ=WEEKLY;INTERVAL=2;BYDAY=FR" in result.output
        assert "rrule: FREQ=WEEKLY;INTERVAL=2;BYDAY=FR" in f.read_text()


class TestVersionFlag:
    """Tests for the version flag."""

    def test_version_flag(self, cli_runner):
        """Test --version flag."""
        result = cli_runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        # Should contain version number
        assert "1.0.0" in result.output or "version" in result.output.lower()


class TestHelpCommands:
    """Tests for help output."""

    def test_main_help(self, cli_runner):
        """Test main help output."""
        result = cli_runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "validate" in result.output
        assert "list" in result.output
        assert "generate" in result.output
        assert "amortize" in result.output
        assert "init" in result.output

    def test_validate_help(self, cli_runner):
        """Test validate command help."""
        result = cli_runner.invoke(main, ["validate", "--help"])
        assert result.exit_code == 0
        assert "Validate schedule files" in result.output

    def test_list_help(self, cli_runner):
        """Test list command help."""
        result = cli_runner.invoke(main, ["list", "--help"])
        assert result.exit_code == 0
        assert "List all schedules" in result.output

    def test_generate_help(self, cli_runner):
        """Test generate command help."""
        result = cli_runner.invoke(main, ["generate", "--help"])
        assert result.exit_code == 0
        assert "Generate expected occurrence dates" in result.output


class TestAmortizeCommand:
    """Tests for amortize command."""

    def test_amortize_table_format(self, cli_runner, tmp_path):
        """Should display amortization table."""
        # Create schedule with amortization
        schedules_dir = tmp_path / "schedules"
        schedules_dir.mkdir()
        (schedules_dir / "test-loan.yaml").write_text("""
id: test-loan
enabled: true
match:
  account: Assets:Checking
  payee_pattern: "Loan"
recurrence:
  frequency: MONTHLY
  start_date: 2024-01-01
  day_of_month: 1
amortization:
  principal: 10000.00
  annual_rate: 0.06
  term_months: 12
  start_date: 2024-01-01
transaction:
  payee: "Loan Payment"
  narration: "Monthly loan payment"
  metadata:
    schedule_id: test-loan
  postings:
    - account: Assets:Checking
      amount: null
    - account: Expenses:Interest
      amount: null
    - account: Liabilities:Loan
      amount: null
""")

        result = cli_runner.invoke(
            main,
            [
                "amortize",
                "test-loan",
                "--schedules-path",
                str(schedules_dir),
                "--limit",
                "3",
            ],
        )

        assert result.exit_code == 0
        assert "Schedule: test-loan" in result.output
        assert "Loan Amount: $10,000.00" in result.output
        assert "Interest Rate: 6.000%" in result.output
        assert "Term: 12 months" in result.output
        assert "Monthly Payment:" in result.output
        assert "Total Interest:" in result.output
        # Check table headers
        assert "Payment" in result.output
        assert "Principal" in result.output
        assert "Interest" in result.output
        assert "Balance" in result.output

    def test_amortize_summary_only(self, cli_runner, tmp_path):
        """Should show summary without table."""
        schedules_dir = tmp_path / "schedules"
        schedules_dir.mkdir()
        (schedules_dir / "test-loan.yaml").write_text("""
id: test-loan
enabled: true
match:
  account: Assets:Checking
  payee_pattern: "Loan"
recurrence:
  frequency: MONTHLY
  start_date: 2024-01-01
  day_of_month: 1
amortization:
  principal: 10000.00
  annual_rate: 0.06
  term_months: 12
  start_date: 2024-01-01
transaction:
  payee: "Loan Payment"
  metadata:
    schedule_id: test-loan
  postings:
    - account: Assets:Checking
    - account: Expenses:Interest
    - account: Liabilities:Loan
""")

        result = cli_runner.invoke(
            main,
            [
                "amortize",
                "test-loan",
                "--schedules-path",
                str(schedules_dir),
                "--summary-only",
            ],
        )

        assert result.exit_code == 0
        assert "Schedule: test-loan" in result.output
        assert "Total Interest:" in result.output
        # Should not have table headers
        assert result.output.count("Payment") <= 1  # Only in summary line

    def test_amortize_csv_format(self, cli_runner, tmp_path):
        """Should output CSV format."""
        schedules_dir = tmp_path / "schedules"
        schedules_dir.mkdir()
        (schedules_dir / "test-loan.yaml").write_text("""
id: test-loan
enabled: true
match:
  account: Assets:Checking
  payee_pattern: "Loan"
recurrence:
  frequency: MONTHLY
  start_date: 2024-01-01
  day_of_month: 1
amortization:
  principal: 10000.00
  annual_rate: 0.06
  term_months: 12
  start_date: 2024-01-01
transaction:
  payee: "Loan Payment"
  metadata:
    schedule_id: test-loan
  postings:
    - account: Assets:Checking
    - account: Expenses:Interest
    - account: Liabilities:Loan
""")

        result = cli_runner.invoke(
            main,
            [
                "amortize",
                "test-loan",
                "--schedules-path",
                str(schedules_dir),
                "--format",
                "csv",
                "--limit",
                "3",
            ],
        )

        assert result.exit_code == 0
        assert "#,Date,Payment,Principal,Interest,Balance" in result.output
        assert "1,2024-01-01," in result.output

    def test_amortize_json_format(self, cli_runner, tmp_path):
        """Should output JSON format."""
        schedules_dir = tmp_path / "schedules"
        schedules_dir.mkdir()
        (schedules_dir / "test-loan.yaml").write_text("""
id: test-loan
enabled: true
match:
  account: Assets:Checking
  payee_pattern: "Loan"
recurrence:
  frequency: MONTHLY
  start_date: 2024-01-01
  day_of_month: 1
amortization:
  principal: 10000.00
  annual_rate: 0.06
  term_months: 12
  start_date: 2024-01-01
transaction:
  payee: "Loan Payment"
  metadata:
    schedule_id: test-loan
  postings:
    - account: Assets:Checking
    - account: Expenses:Interest
    - account: Liabilities:Loan
""")

        result = cli_runner.invoke(
            main,
            [
                "amortize",
                "test-loan",
                "--schedules-path",
                str(schedules_dir),
                "--format",
                "json",
                "--limit",
                "2",
            ],
        )

        assert result.exit_code == 0
        # Parse JSON to validate
        output_json = json.loads(result.output)
        assert "summary" in output_json
        assert "payments" in output_json
        assert output_json["summary"]["schedule_id"] == "test-loan"
        assert len(output_json["payments"]) == 2

    def test_amortize_schedule_not_found(self, cli_runner, tmp_path):
        """Should error if schedule not found."""
        schedules_dir = tmp_path / "schedules"
        schedules_dir.mkdir()

        result = cli_runner.invoke(
            main, ["amortize", "nonexistent", "--schedules-path", str(schedules_dir)]
        )

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_amortize_no_amortization_config(self, cli_runner, tmp_path):
        """Should error if schedule has no amortization."""
        schedules_dir = tmp_path / "schedules"
        schedules_dir.mkdir()
        (schedules_dir / "test-schedule.yaml").write_text("""
id: test-schedule
enabled: true
match:
  account: Assets:Checking
  payee_pattern: "Test"
recurrence:
  frequency: MONTHLY
  start_date: 2024-01-01
  day_of_month: 1
transaction:
  payee: "Test"
  metadata:
    schedule_id: test-schedule
  postings:
    - account: Assets:Checking
    - account: Expenses:Test
""")

        result = cli_runner.invoke(
            main,
            ["amortize", "test-schedule", "--schedules-path", str(schedules_dir)],
        )

        assert result.exit_code == 1
        assert "does not have amortization configured" in result.output


class TestSkipCommand:
    """Tests for the skip CLI command."""

    def test_skip_single_date(self, cli_runner, schedules_directory):
        """Generate skip marker for a single date."""
        result = cli_runner.invoke(
            main,
            [
                "skip",
                "rent-payment",
                "2026-02-01",
                "--schedules-path",
                str(schedules_directory),
            ],
        )

        assert result.exit_code == 0
        assert "2026-02-01" in result.output
        assert "#skipped" in result.output  # #skipped tag indicator
        assert "RiverBank Properties" in result.output
        assert "[SKIPPED]" in result.output
        assert "schedule_id" in result.output
        assert "rent-payment" in result.output

    def test_skip_multiple_dates(self, cli_runner, schedules_directory):
        """Generate skip markers for multiple dates."""
        result = cli_runner.invoke(
            main,
            [
                "skip",
                "rent-payment",
                "2026-02-01",
                "2026-03-01",
                "--schedules-path",
                str(schedules_directory),
            ],
        )

        assert result.exit_code == 0
        assert "2026-02-01" in result.output
        assert "2026-03-01" in result.output

    def test_skip_with_reason(self, cli_runner, schedules_directory):
        """Skip marker includes reason in narration."""
        result = cli_runner.invoke(
            main,
            [
                "skip",
                "rent-payment",
                "2026-02-01",
                "--reason",
                "Postponed to next month",
                "--schedules-path",
                str(schedules_directory),
            ],
        )

        assert result.exit_code == 0
        assert "Postponed to next month" in result.output
        assert "[SKIPPED]" in result.output

    def test_skip_invalid_schedule_id(self, cli_runner, schedules_directory):
        """Error when schedule_id not found."""
        result = cli_runner.invoke(
            main,
            [
                "skip",
                "nonexistent-schedule",
                "2026-02-01",
                "--schedules-path",
                str(schedules_directory),
            ],
        )

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_skip_invalid_date_format(self, cli_runner, schedules_directory):
        """Error when date format is invalid."""
        result = cli_runner.invoke(
            main,
            [
                "skip",
                "rent-payment",
                "02-01-2026",  # Wrong format
                "--schedules-path",
                str(schedules_directory),
            ],
        )

        assert result.exit_code == 1
        assert "Invalid date format" in result.output

    def test_skip_output_to_file(self, cli_runner, schedules_directory, tmp_path):
        """Skip markers can be appended to a file."""
        output_file = tmp_path / "skips.beancount"
        output_file.write_text("")  # Create empty file

        result = cli_runner.invoke(
            main,
            [
                "skip",
                "rent-payment",
                "2026-02-01",
                "--schedules-path",
                str(schedules_directory),
                "--output",
                str(output_file),
            ],
        )

        assert result.exit_code == 0
        content = output_file.read_text()
        assert "2026-02-01" in content
        assert "rent-payment" in content

    def test_skip_requires_dates(self, cli_runner, schedules_directory):
        """Error when no dates provided."""
        result = cli_runner.invoke(
            main,
            [
                "skip",
                "rent-payment",
                "--schedules-path",
                str(schedules_directory),
            ],
        )

        assert result.exit_code != 0
        assert "Missing argument" in result.output or "DATES" in result.output

    def test_skip_select_requires_ledger(self, cli_runner, schedules_directory):
        """Error when --select used without --ledger."""
        result = cli_runner.invoke(
            main,
            [
                "skip",
                "--select",
                "--schedules-path",
                str(schedules_directory),
            ],
        )

        assert result.exit_code != 0
        assert "ledger" in result.output.lower()
