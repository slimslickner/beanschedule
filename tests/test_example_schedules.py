"""Tests validating example schedules."""

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from beanschedule.cli.commands import validate
from beanschedule.loader import load_schedules_from_path
from beanschedule.schema import Schedule

# Standard path to examples/schedules directory
EXAMPLES_SCHEDULES_DIR = Path(__file__).parent.parent / "examples" / "schedules"


def get_example_schedule_files(schedules_dir: Path) -> list[Path]:
    """Get all schedule YAML files (excluding _config.yaml)."""
    schedule_files = sorted(schedules_dir.glob("*.yaml"))
    return [f for f in schedule_files if f.name != "_config.yaml"]


class TestExampleSchedulesValidation:
    """Validate each example schedule individually."""

    @pytest.mark.parametrize(
        "schedule_file",
        get_example_schedule_files(EXAMPLES_SCHEDULES_DIR),
        ids=lambda f: f.name,
    )
    def test_schedule_file_is_valid_yaml(self, schedule_file):
        """Verify each schedule file is valid YAML."""
        with open(schedule_file) as f:
            data = yaml.safe_load(f)
        assert data is not None, (
            f"Schedule {schedule_file.name} is empty or invalid YAML"
        )

    @pytest.mark.parametrize(
        "schedule_file",
        get_example_schedule_files(EXAMPLES_SCHEDULES_DIR),
        ids=lambda f: f.name,
    )
    def test_schedule_conforms_to_schema(self, schedule_file):
        """Verify each schedule conforms to the schema."""
        with open(schedule_file) as f:
            data = yaml.safe_load(f)

        # Should not raise if valid
        schedule = Schedule.model_validate(data)

        # Basic sanity checks
        assert schedule.id, f"Schedule in {schedule_file.name} must have an id"
        assert schedule.match, (
            f"Schedule in {schedule_file.name} must have match criteria"
        )
        assert schedule.match.account, (
            f"Schedule in {schedule_file.name} must have match.account"
        )
        assert schedule.recurrence, (
            f"Schedule in {schedule_file.name} must have recurrence"
        )
        assert schedule.transaction, (
            f"Schedule in {schedule_file.name} must have transaction template"
        )

    @pytest.mark.parametrize(
        "schedule_file",
        get_example_schedule_files(EXAMPLES_SCHEDULES_DIR),
        ids=lambda f: f.name,
    )
    def test_schedule_recurrence_is_valid(self, schedule_file):
        """Verify recurrence rule is valid for the given frequency."""
        with open(schedule_file) as f:
            data = yaml.safe_load(f)
        schedule = Schedule.model_validate(data)

        # Verify start date is set
        assert schedule.recurrence.start_date, (
            f"Schedule in {schedule_file.name} must have start_date"
        )

        # If end_date is set, it should be after start_date
        if schedule.recurrence.end_date:
            assert schedule.recurrence.end_date >= schedule.recurrence.start_date, (
                f"Schedule in {schedule_file.name} has end_date before start_date"
            )


class TestExampleSchedulesIntegration:
    """Integration tests for all example schedules."""

    def test_all_example_schedules_validate_with_cli(self):
        """Verify all example schedules pass CLI validation."""
        runner = CliRunner()
        result = runner.invoke(validate, [str(EXAMPLES_SCHEDULES_DIR)])

        assert result.exit_code == 0, f"Validation failed:\n{result.output}"
        assert "Validation successful!" in result.output
        assert "All schedules are valid!" in result.output

    def test_example_schedules_can_be_loaded(self):
        """Verify example schedules can be loaded as a complete ScheduleFile."""
        schedule_file = load_schedules_from_path(EXAMPLES_SCHEDULES_DIR)

        assert schedule_file is not None, "Failed to load example schedules"
        assert len(schedule_file.schedules) >= 10, (
            f"Expected at least 10 example schedules, got {len(schedule_file.schedules)}"
        )

    def test_example_schedules_have_no_duplicates(self):
        """Verify no duplicate schedule IDs in examples."""
        schedule_file = load_schedules_from_path(EXAMPLES_SCHEDULES_DIR)
        assert schedule_file is not None, "Failed to load schedules"

        schedule_ids = [s.id for s in schedule_file.schedules]
        duplicates = [sid for sid in schedule_ids if schedule_ids.count(sid) > 1]

        assert not duplicates, f"Found duplicate schedule IDs: {set(duplicates)}"

    def test_example_schedules_cover_different_frequencies(self):
        """Verify example schedules demonstrate different recurrence patterns."""
        schedule_file = load_schedules_from_path(EXAMPLES_SCHEDULES_DIR)
        assert schedule_file is not None, "Failed to load schedules"

        rrules = set()
        for schedule in schedule_file.schedules:
            rrules.add(schedule.recurrence.rrule)

        # Should have multiple distinct rrule patterns
        assert len(rrules) >= 3, (
            f"Examples should demonstrate multiple recurrence patterns, got: {rrules}"
        )

    def test_example_schedules_demonstrate_different_matching_strategies(self):
        """Verify example schedules show different amount matching strategies."""
        schedule_file = load_schedules_from_path(EXAMPLES_SCHEDULES_DIR)
        assert schedule_file is not None, "Failed to load schedules"

        has_fixed_amount = False
        has_amount_range = False

        for schedule in schedule_file.schedules:
            if schedule.match.amount is not None and schedule.match.amount_min is None:
                has_fixed_amount = True
            if (
                schedule.match.amount_min is not None
                and schedule.match.amount_max is not None
            ):
                has_amount_range = True

        assert has_fixed_amount, (
            "Examples should demonstrate fixed amount with tolerance"
        )
        assert has_amount_range, "Examples should demonstrate amount range matching"
