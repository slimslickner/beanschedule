"""Tests for YAML to forecast migration."""

from datetime import date
from pathlib import Path

from click.testing import CliRunner

from beanschedule.cli import main


class TestMigrateCommand:
    """Tests for migrate command."""

    def test_migrate_simple_yaml_to_stdout(self, tmp_path):
        """Should convert simple YAML to forecast format."""
        # Create YAML file
        yaml_file = tmp_path / "schedules.yaml"
        yaml_file.write_text(
            """
version: "1.0"
schedules:
  - id: rent-monthly
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: ".*LANDLORD.*"
      amount: -1500.00
      amount_tolerance: 0.00
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

        runner = CliRunner()
        result = runner.invoke(main, ["migrate", str(yaml_file)])

        assert result.exit_code == 0
        assert "Found 1 schedule(s)" in result.output
        # Date will be next occurrence from today, check for format and content
        assert '# "Rent Payment" "Monthly rent [MONTHLY]"' in result.output
        assert 'schedule-id: "rent-monthly"' in result.output
        assert 'schedule-frequency: "MONTHLY"' in result.output
        assert 'schedule-day-of-month: "1"' in result.output
        assert 'schedule-match-account: "Assets:Checking"' in result.output
        # Verify date is on day 1 of the month (matching recurrence pattern)
        import re
        date_match = re.search(r'(\d{4}-\d{2}-01) # "Rent Payment"', result.output)
        assert date_match, "Forecast date should be on day 1 of the month"

    def test_migrate_to_file(self, tmp_path):
        """Should write output to file when -o specified."""
        # Create YAML file
        yaml_file = tmp_path / "schedules.yaml"
        yaml_file.write_text(
            """
version: "1.0"
schedules:
  - id: test
    match:
      account: Assets:Checking
      payee_pattern: ".*TEST.*"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 15
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

        output_file = tmp_path / "Forecast.bean"
        runner = CliRunner()
        result = runner.invoke(main, ["migrate", str(yaml_file), "-o", str(output_file)])

        assert result.exit_code == 0
        assert output_file.exists()

        content = output_file.read_text()
        # Date should be on day 15 of the month (matching recurrence pattern)
        assert '# "Test"' in content
        assert 'schedule-id: "test"' in content
        assert 'schedule-day-of-month: "15"' in content
        # Verify date ends with -15 (day 15 of month)
        import re
        date_match = re.search(r'(\d{4}-\d{2}-15) # "Test"', content)
        assert date_match, "Forecast date should be on day 15 of the month"

    def test_migrate_multiple_schedules(self, tmp_path):
        """Should convert multiple schedules."""
        yaml_file = tmp_path / "schedules.yaml"
        yaml_file.write_text(
            """
version: "1.0"
schedules:
  - id: rent
    match:
      account: Assets:Checking
      payee_pattern: ".*RENT.*"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    transaction:
      payee: "Rent"
      narration: ""
      metadata:
        schedule_id: rent
      postings:
        - account: Expenses:Rent
          amount: 1000.00
        - account: Assets:Checking

  - id: electric
    match:
      account: Assets:Checking
      payee_pattern: ".*ELECTRIC.*"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-05
      day_of_month: 5
    transaction:
      payee: "Electric"
      narration: ""
      metadata:
        schedule_id: electric
      postings:
        - account: Expenses:Electric
          amount: 50.00
        - account: Assets:Checking
"""
        )

        runner = CliRunner()
        result = runner.invoke(main, ["migrate", str(yaml_file)])

        assert result.exit_code == 0
        assert "Found 2 schedule(s)" in result.output
        assert 'schedule-id: "rent"' in result.output
        assert 'schedule-id: "electric"' in result.output

    def test_migrate_with_grouping_by_frequency(self, tmp_path):
        """Should group schedules by frequency."""
        yaml_file = tmp_path / "schedules.yaml"
        yaml_file.write_text(
            """
version: "1.0"
schedules:
  - id: monthly-1
    match:
      account: Assets:Checking
      payee_pattern: ".*"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    transaction:
      payee: "Monthly 1"
      narration: ""
      metadata:
        schedule_id: monthly-1
      postings:
        - account: Expenses:Test
          amount: 100.00
        - account: Assets:Checking

  - id: weekly-1
    match:
      account: Assets:Checking
      payee_pattern: ".*"
    recurrence:
      frequency: WEEKLY
      start_date: 2024-01-01
      day_of_week: MON
    transaction:
      payee: "Weekly 1"
      narration: ""
      metadata:
        schedule_id: weekly-1
      postings:
        - account: Expenses:Test
          amount: 50.00
        - account: Assets:Checking
"""
        )

        runner = CliRunner()
        result = runner.invoke(main, ["migrate", str(yaml_file), "--group-by", "frequency"])

        assert result.exit_code == 0
        assert "; === MONTHLY ===" in result.output
        assert "; === WEEKLY ===" in result.output

    def test_migrate_advanced_recurrence_monthly_on_days(self, tmp_path):
        """Should convert MONTHLY_ON_DAYS recurrence."""
        yaml_file = tmp_path / "schedules.yaml"
        yaml_file.write_text(
            """
version: "1.0"
schedules:
  - id: paycheck
    match:
      account: Assets:Checking
      payee_pattern: ".*EMPLOYER.*"
    recurrence:
      frequency: MONTHLY_ON_DAYS
      start_date: 2024-01-05
      days_of_month: [5, 20]
    transaction:
      payee: "Paycheck"
      narration: ""
      metadata:
        schedule_id: paycheck
      postings:
        - account: Assets:Checking
          amount: 2500.00
        - account: Income:Salary
"""
        )

        runner = CliRunner()
        result = runner.invoke(main, ["migrate", str(yaml_file)])

        assert result.exit_code == 0
        assert 'schedule-frequency: "MONTHLY_ON_DAYS"' in result.output
        assert 'schedule-days-of-month: "5,20"' in result.output

    def test_migrate_nth_weekday(self, tmp_path):
        """Should convert NTH_WEEKDAY recurrence."""
        yaml_file = tmp_path / "schedules.yaml"
        yaml_file.write_text(
            """
version: "1.0"
schedules:
  - id: meeting
    match:
      account: Assets:Checking
      payee_pattern: ".*"
    recurrence:
      frequency: NTH_WEEKDAY
      start_date: 2024-01-09
      nth_occurrence: 2
      day_of_week: TUE
    transaction:
      payee: "Meeting"
      narration: ""
      metadata:
        schedule_id: meeting
      postings:
        - account: Expenses:Dining
          amount: 50.00
        - account: Assets:Checking
"""
        )

        runner = CliRunner()
        result = runner.invoke(main, ["migrate", str(yaml_file)])

        assert result.exit_code == 0
        assert 'schedule-frequency: "NTH_WEEKDAY"' in result.output
        assert 'schedule-nth-occurrence: "2"' in result.output
        assert 'schedule-day-of-week: "TUE"' in result.output

    def test_migrate_with_end_date(self, tmp_path):
        """Should include end_date if specified."""
        yaml_file = tmp_path / "schedules.yaml"
        yaml_file.write_text(
            """
version: "1.0"
schedules:
  - id: limited
    match:
      account: Assets:Checking
      payee_pattern: ".*"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      end_date: 2024-06-30
      day_of_month: 1
    transaction:
      payee: "Limited"
      narration: ""
      metadata:
        schedule_id: limited
      postings:
        - account: Expenses:Test
          amount: 100.00
        - account: Assets:Checking
"""
        )

        runner = CliRunner()
        result = runner.invoke(main, ["migrate", str(yaml_file)])

        assert result.exit_code == 0
        assert 'schedule-until: "2024-06-30"' in result.output

    def test_migrate_invalid_path(self):
        """Should error on invalid path."""
        runner = CliRunner()
        result = runner.invoke(main, ["migrate", "nonexistent.yaml"])

        assert result.exit_code != 0

    def test_migrate_empty_yaml(self, tmp_path):
        """Should error on empty YAML file."""
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text(
            """
version: "1.0"
schedules: []
"""
        )

        runner = CliRunner()
        result = runner.invoke(main, ["migrate", str(yaml_file)])

        assert result.exit_code != 0
        assert "No schedules found" in result.output

    def test_migrate_match_account_gets_amount(self, tmp_path):
        """Should ensure match account posting uses match.amount value."""
        yaml_file = tmp_path / "schedules.yaml"
        yaml_file.write_text(
            """
version: "1.0"
schedules:
  - id: test
    match:
      account: Assets:Checking
      payee_pattern: ".*TEST.*"
      amount: -100.00
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
        - account: Assets:Checking
          # No amount specified - should use match.amount (-100.00)
"""
        )

        runner = CliRunner()
        result = runner.invoke(main, ["migrate", str(yaml_file)])

        assert result.exit_code == 0
        # Check that match account (Assets:Checking) has explicit amount from match.amount
        assert "Assets:Checking" in result.output
        # schedule-amount metadata should have -100.0
        assert 'schedule-amount: "-100.0"' in result.output
        # The posting should show -100.0 USD (from match.amount)
        assert "Assets:Checking  -100.0 USD" in result.output

    def test_migrate_posting_narrations(self, tmp_path):
        """Should migrate posting-level narrations to posting metadata."""
        yaml_file = tmp_path / "schedules.yaml"
        yaml_file.write_text(
            """
version: "1.0"
schedules:
  - id: test
    match:
      account: Assets:Checking
      payee_pattern: ".*TEST.*"
      amount: -100.00
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

        runner = CliRunner()
        result = runner.invoke(main, ["migrate", str(yaml_file)])

        assert result.exit_code == 0
        # Posting narrations should appear as indented metadata under each posting
        assert "Expenses:Test" in result.output
        assert 'narration: "Test expense note"' in result.output
        assert "Assets:Checking" in result.output
        assert 'narration: "Payment from checking"' in result.output
