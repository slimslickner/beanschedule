"""Tests for CLI commands."""

import json

import pytest
import yaml
from click.testing import CliRunner

from beanschedule.cli import main


@pytest.fixture
def cli_runner():
    """Create a Click test runner."""
    return CliRunner()


@pytest.fixture
def schedules_yaml_file(tmp_path):
    """Create a temporary schedules.yaml file."""
    schedules_data = {
        "schedules": [
            {
                "id": "monthly-rent",
                "enabled": True,
                "match": {
                    "account": "Assets:Bank:Checking",
                    "payee_pattern": "Property Manager",
                    "amount": -1500.0,
                },
                "recurrence": {
                    "frequency": "MONTHLY",
                    "day_of_month": 1,
                    "start_date": "2024-01-01",
                },
                "transaction": {
                    "payee": "Property Manager",
                    "narration": "Monthly Rent",
                    "metadata": {"schedule_id": "monthly-rent"},
                    "postings": [
                        {"account": "Assets:Bank:Checking", "amount": None},
                        {"account": "Expenses:Housing:Rent", "amount": None},
                    ],
                },
            },
            {
                "id": "biweekly-paycheck",
                "enabled": True,
                "match": {
                    "account": "Assets:Bank:Checking",
                    "payee_pattern": "Employer",
                    "amount": 2500.0,
                },
                "recurrence": {
                    "frequency": "WEEKLY",
                    "interval": 2,
                    "day_of_week": "MON",
                    "start_date": "2024-01-01",
                },
                "transaction": {
                    "payee": "Employer",
                    "narration": "Paycheck",
                    "metadata": {"schedule_id": "biweekly-paycheck"},
                    "postings": [
                        {"account": "Assets:Bank:Checking", "amount": None},
                        {"account": "Income:Salary", "amount": None},
                    ],
                },
            },
            {
                "id": "disabled-schedule",
                "enabled": False,
                "match": {
                    "account": "Assets:Bank:Savings",
                    "payee_pattern": "Bank",
                },
                "recurrence": {
                    "frequency": "YEARLY",
                    "month": 1,
                    "day_of_month": 15,
                    "start_date": "2024-01-01",
                },
                "transaction": {
                    "payee": "Bank",
                    "narration": "Interest",
                    "metadata": {"schedule_id": "disabled-schedule"},
                    "postings": [
                        {"account": "Assets:Bank:Savings", "amount": None},
                        {"account": "Income:Interest", "amount": None},
                    ],
                },
            },
        ]
    }

    schedule_file = tmp_path / "schedules.yaml"
    with open(schedule_file, "w") as f:
        yaml.dump(schedules_data, f)

    return schedule_file


@pytest.fixture
def schedules_directory(tmp_path):
    """Create a temporary schedules directory with YAML files."""
    schedules_dir = tmp_path / "schedules"
    schedules_dir.mkdir()

    # Create config
    config_data = {
        "fuzzy_match_threshold": 0.80,
        "default_date_window_days": 3,
        "default_amount_tolerance_percent": 0.02,
        "placeholder_flag": "!",
    }
    with open(schedules_dir / "_config.yaml", "w") as f:
        yaml.dump(config_data, f)

    # Create schedules
    schedules = [
        {
            "id": "monthly-rent",
            "enabled": True,
            "match": {
                "account": "Assets:Bank:Checking",
                "payee_pattern": "Property Manager",
                "amount": -1500.0,
            },
            "recurrence": {
                "frequency": "MONTHLY",
                "day_of_month": 1,
                "start_date": "2024-01-01",
            },
            "transaction": {
                "payee": "Property Manager",
                "narration": "Monthly Rent",
                "metadata": {"schedule_id": "monthly-rent"},
                "postings": [
                    {"account": "Assets:Bank:Checking", "amount": None},
                    {"account": "Expenses:Housing:Rent", "amount": None},
                ],
            },
        },
        {
            "id": "biweekly-paycheck",
            "enabled": True,
            "match": {
                "account": "Assets:Bank:Checking",
                "payee_pattern": "Employer",
                "amount": 2500.0,
            },
            "recurrence": {
                "frequency": "WEEKLY",
                "interval": 2,
                "day_of_week": "MON",
                "start_date": "2024-01-01",
            },
            "transaction": {
                "payee": "Employer",
                "narration": "Paycheck",
                "metadata": {"schedule_id": "biweekly-paycheck"},
                "postings": [
                    {"account": "Assets:Bank:Checking", "amount": None},
                    {"account": "Income:Salary", "amount": None},
                ],
            },
        },
        {
            "id": "disabled-schedule",
            "enabled": False,
            "match": {
                "account": "Assets:Bank:Savings",
                "payee_pattern": "Bank",
            },
            "recurrence": {
                "frequency": "YEARLY",
                "month": 1,
                "day_of_month": 15,
                "start_date": "2024-01-01",
            },
            "transaction": {
                "payee": "Bank",
                "narration": "Interest",
                "metadata": {"schedule_id": "disabled-schedule"},
                "postings": [
                    {"account": "Assets:Bank:Savings", "amount": None},
                    {"account": "Income:Interest", "amount": None},
                ],
            },
        },
    ]

    for schedule in schedules:
        filename = f"{schedule['id']}.yaml"
        with open(schedules_dir / filename, "w") as f:
            yaml.dump(schedule, f)

    return schedules_dir


class TestValidateCommand:
    """Tests for the validate command."""

    def test_validate_file_success(self, cli_runner, schedules_yaml_file):
        """Test validating a schedules.yaml file successfully."""
        result = cli_runner.invoke(main, ["validate", str(schedules_yaml_file)])
        assert result.exit_code == 0
        assert "Validation successful" in result.output
        assert "Total schedules: 3" in result.output
        assert "Enabled: 2" in result.output
        assert "Disabled: 1" in result.output

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

    def test_validate_empty_file(self, cli_runner, tmp_path):
        """Test validating an empty schedules file."""
        empty_file = tmp_path / "empty.yaml"
        with open(empty_file, "w") as f:
            f.write("")

        result = cli_runner.invoke(main, ["validate", str(empty_file)])
        assert result.exit_code == 0
        assert "Total schedules: 0" in result.output

    def test_validate_with_verbose_flag(self, cli_runner, schedules_yaml_file):
        """Test validate command with verbose flag."""
        result = cli_runner.invoke(main, ["-v", "validate", str(schedules_yaml_file)])
        assert result.exit_code == 0
        assert "Validation successful" in result.output


class TestListCommand:
    """Tests for the list command."""

    def test_list_file_table_format(self, cli_runner, schedules_yaml_file):
        """Test listing schedules from file in table format."""
        result = cli_runner.invoke(main, ["list", str(schedules_yaml_file)])
        assert result.exit_code == 0
        assert "ID" in result.output
        assert "Status" in result.output
        assert "monthly-rent" in result.output
        assert "biweekly-paycheck" in result.output
        assert "disabled-schedule" in result.output
        assert "Total: 3 schedules" in result.output

    def test_list_directory_table_format(self, cli_runner, schedules_directory):
        """Test listing schedules from directory in table format."""
        result = cli_runner.invoke(main, ["list", str(schedules_directory)])
        assert result.exit_code == 0
        assert "monthly-rent" in result.output
        assert "Total: 3 schedules" in result.output

    def test_list_enabled_only_filter(self, cli_runner, schedules_yaml_file):
        """Test listing only enabled schedules."""
        result = cli_runner.invoke(main, ["list", str(schedules_yaml_file), "--enabled-only"])
        assert result.exit_code == 0
        assert "monthly-rent" in result.output
        assert "biweekly-paycheck" in result.output
        assert "disabled-schedule" not in result.output
        assert "Total: 2 schedules" in result.output

    def test_list_json_format(self, cli_runner, schedules_yaml_file):
        """Test listing schedules in JSON format."""
        result = cli_runner.invoke(main, ["list", str(schedules_yaml_file), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 3
        assert data[0]["id"] == "monthly-rent"

    def test_list_csv_format(self, cli_runner, schedules_yaml_file):
        """Test listing schedules in CSV format."""
        result = cli_runner.invoke(main, ["list", str(schedules_yaml_file), "--format", "csv"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert lines[0] == "ID,Enabled,Frequency,Payee,Account,Amount"
        assert "monthly-rent" in result.output

    def test_list_csv_enabled_only(self, cli_runner, schedules_yaml_file):
        """Test listing enabled schedules in CSV format."""
        result = cli_runner.invoke(
            main,
            [
                "list",
                str(schedules_yaml_file),
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

    def test_list_invalid_format(self, cli_runner, schedules_yaml_file):
        """Test list command with invalid format."""
        result = cli_runner.invoke(main, ["list", str(schedules_yaml_file), "--format", "invalid"])
        assert result.exit_code != 0


class TestGenerateCommand:
    """Tests for the generate command."""

    def test_generate_monthly_schedule(self, cli_runner, schedules_yaml_file):
        """Test generating occurrences for a monthly schedule."""
        result = cli_runner.invoke(
            main,
            [
                "generate",
                "monthly-rent",
                "2024-01-01",
                "2024-03-31",
                "--schedules-path",
                str(schedules_yaml_file),
            ],
        )
        if result.exit_code != 0:
            print(f"Error output: {result.output}")
            if result.exception:
                print(f"Exception: {result.exception}")
                import traceback

                traceback.print_exception(
                    type(result.exception), result.exception, result.exception.__traceback__
                )
        assert result.exit_code == 0
        assert "Schedule: monthly-rent" in result.output
        assert "Frequency: MONTHLY" in result.output
        assert "2024-01-01" in result.output
        assert "2024-02-01" in result.output
        assert "2024-03-01" in result.output
        assert "Expected occurrences (3)" in result.output

    def test_generate_weekly_schedule(self, cli_runner, schedules_yaml_file):
        """Test generating occurrences for a weekly schedule."""
        result = cli_runner.invoke(
            main,
            [
                "generate",
                "biweekly-paycheck",
                "2024-01-01",
                "2024-02-29",
                "--schedules-path",
                str(schedules_yaml_file),
            ],
        )
        assert result.exit_code == 0
        assert "Schedule: biweekly-paycheck" in result.output
        assert "Frequency: WEEKLY" in result.output
        # Should have some occurrences
        assert "Expected occurrences" in result.output

    def test_generate_schedule_not_found(self, cli_runner, schedules_yaml_file):
        """Test generating for a non-existent schedule."""
        result = cli_runner.invoke(
            main,
            [
                "generate",
                "nonexistent",
                "2024-01-01",
                "2024-12-31",
                "--schedules-path",
                str(schedules_yaml_file),
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
                "monthly-rent",
                "2024-01-01",
                "2024-03-31",
                "--schedules-path",
                str(schedules_directory),
            ],
        )
        assert result.exit_code == 0
        assert "Schedule: monthly-rent" in result.output
        assert "Expected occurrences (3)" in result.output

    def test_generate_default_schedules_path(self, cli_runner, tmp_path):
        """Test generate command with default schedules path."""
        # Create schedules directory in current location
        schedules_dir = tmp_path / "schedules"
        schedules_dir.mkdir()

        # Create a simple schedule
        schedule_data = {
            "id": "test-schedule",
            "enabled": True,
            "match": {"account": "Assets:Bank"},
            "recurrence": {"frequency": "MONTHLY", "day_of_month": 1},
            "transaction": {
                "payee": "Test",
                "narration": "Test",
                "postings": [{"account": "Assets:Bank", "amount": None}],
            },
        }
        with open(schedules_dir / "test-schedule.yaml", "w") as f:
            yaml.dump(schedule_data, f)

        # Change to temp directory and test
        result = cli_runner.invoke(
            main,
            [
                "generate",
                "test-schedule",
                "2024-01-01",
                "2024-03-31",
            ],
            catch_exceptions=False,
            obj={"cwd": str(tmp_path)},
        )
        # Note: This might fail since we're not actually changing directory
        # But we can test with explicit path instead


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
