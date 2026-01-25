"""Command-line interface for beanschedule."""

import csv
import json
import logging
import sys
import traceback
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import click

from . import __version__
from .loader import load_schedules_file, load_schedules_from_directory
from .recurrence import RecurrenceEngine

logger = logging.getLogger(__name__)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.version_option(version=__version__)
def main(verbose: bool):
    """Beanschedule - Scheduled transaction framework for Beancount."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


@main.command()
@click.argument("path", type=click.Path(exists=True))
def validate(path: str):
    """Validate schedule files for syntax and schema compliance.

    PATH can be either a schedules.yaml file or a schedules/ directory.

    Examples:
        beanschedule validate schedules.yaml
        beanschedule validate schedules/
    """
    path_obj = Path(path)

    click.echo(f"Validating schedules from: {path_obj}")

    try:
        # Try loading as file or directory
        if path_obj.is_file():
            schedule_file = load_schedules_file(path_obj)
        elif path_obj.is_dir():
            schedule_file = load_schedules_from_directory(path_obj)
        else:
            click.echo(f"Error: Path is neither a file nor a directory: {path_obj}", err=True)
            sys.exit(1)

        if schedule_file is None:
            click.echo("Error: No schedules loaded", err=True)
            sys.exit(1)

        # Count schedules
        num_schedules = len(schedule_file.schedules)
        num_enabled = sum(1 for s in schedule_file.schedules if s.enabled)

        # Report results
        click.echo("✓ Validation successful!")
        click.echo(f"  Total schedules: {num_schedules}")
        click.echo(f"  Enabled: {num_enabled}")
        click.echo(f"  Disabled: {num_schedules - num_enabled}")

        # Check for duplicate IDs
        schedule_ids = [s.id for s in schedule_file.schedules]
        duplicates = [sid for sid in schedule_ids if schedule_ids.count(sid) > 1]
        if duplicates:
            click.echo(f"\n⚠ Warning: Duplicate schedule IDs found: {set(duplicates)}", err=True)
            sys.exit(1)

        click.echo("\nAll schedules are valid!")

    except Exception as e:
        click.echo(f"✗ Validation failed: {e}", err=True)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        sys.exit(1)


@main.command(name="list")
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format (default: table)",
)
@click.option("--enabled-only", is_flag=True, help="Show only enabled schedules")
def list_schedules(path: str, output_format: str, enabled_only: bool):
    """List all schedules with details.

    PATH can be either a schedules.yaml file or a schedules/ directory.

    Examples:
        beanschedule list schedules/
        beanschedule list schedules/ --enabled-only
        beanschedule list schedules/ --format json
    """
    path_obj = Path(path)

    try:
        # Load schedules
        if path_obj.is_file():
            schedule_file = load_schedules_file(path_obj)
        elif path_obj.is_dir():
            schedule_file = load_schedules_from_directory(path_obj)
        else:
            click.echo(f"Error: Path is neither a file nor a directory: {path_obj}", err=True)
            sys.exit(1)

        if schedule_file is None:
            click.echo("Error: No schedules loaded", err=True)
            sys.exit(1)

        # Filter schedules
        schedules = schedule_file.schedules
        if enabled_only:
            schedules = [s for s in schedules if s.enabled]

        if not schedules:
            click.echo("No schedules found")
            return

        # Output in requested format
        if output_format == "table":
            _print_schedule_table(schedules)
        elif output_format == "json":
            schedules_data = [s.model_dump(mode="python") for s in schedules]
            click.echo(json.dumps(schedules_data, indent=2, default=str))
        elif output_format == "csv":
            _print_schedule_csv(schedules)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        sys.exit(1)


def _print_schedule_table(schedules: list) -> None:
    """
    Print schedules as a formatted ASCII table.

    Displays schedule ID, enabled/disabled status, recurrence frequency, and payee
    pattern for all schedules. Column widths are auto-calculated based on content.

    Args:
        schedules: List of Schedule objects to display.
    """
    # Calculate column widths
    id_width = max(len(s.id) for s in schedules)
    id_width = max(id_width, len("ID"))

    payee_width = max(len(s.transaction.payee or "") for s in schedules)
    payee_width = max(payee_width, len("Payee"))
    payee_width = min(payee_width, 30)  # Cap at 30

    # Print header
    click.echo(f"{'ID':<{id_width}}  {'Status':<8}  {'Frequency':<12}  {'Payee':<{payee_width}}")
    click.echo("-" * (id_width + 8 + 12 + payee_width + 6))

    # Print schedules
    for s in schedules:
        status = "✓ enabled" if s.enabled else "  disabled"
        frequency = s.recurrence.frequency.value
        payee = (s.transaction.payee or "")[:payee_width]

        click.echo(f"{s.id:<{id_width}}  {status:<8}  {frequency:<12}  {payee:<{payee_width}}")

    click.echo(f"\nTotal: {len(schedules)} schedules")


def _print_schedule_csv(schedules: list) -> None:
    """
    Print schedules as comma-separated values (CSV) to stdout.

    Outputs schedule details in CSV format suitable for import into spreadsheet
    applications. Columns include: ID, Enabled status, Frequency, Payee pattern,
    Account, and Expected amount.

    Args:
        schedules: List of Schedule objects to export.
    """
    writer = csv.writer(sys.stdout)
    writer.writerow(["ID", "Enabled", "Frequency", "Payee", "Account", "Amount"])

    for s in schedules:
        writer.writerow(
            [
                s.id,
                "true" if s.enabled else "false",
                s.recurrence.frequency.value,
                s.transaction.payee or "",
                s.match.account,
                s.match.amount or "",
            ],
        )


@main.command()
@click.argument("schedule_id")
@click.argument("start_date", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.argument("end_date", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option(
    "--schedules-path",
    type=click.Path(exists=True),
    default="schedules",
    help="Path to schedules file or directory (default: schedules)",
)
def generate(schedule_id: str, start_date, end_date, schedules_path: str):
    """Generate expected occurrence dates for a schedule.

    SCHEDULE_ID: The ID of the schedule to generate dates for
    START_DATE: Start date in YYYY-MM-DD format
    END_DATE: End date in YYYY-MM-DD format

    Examples:
        beanschedule generate mortgage-payment 2024-01-01 2024-12-31
        beanschedule generate paycheck 2024-01-01 2024-06-30 --schedules-path my-schedules/
    """
    path_obj = Path(schedules_path)
    start = start_date.date()
    end = end_date.date()

    try:
        # Load schedules
        if path_obj.is_file():
            schedule_file = load_schedules_file(path_obj)
        elif path_obj.is_dir():
            schedule_file = load_schedules_from_directory(path_obj)
        else:
            click.echo(f"Error: Path not found: {path_obj}", err=True)
            sys.exit(1)

        if schedule_file is None:
            click.echo("Error: No schedules loaded", err=True)
            sys.exit(1)

        # Find schedule by ID
        schedule = next((s for s in schedule_file.schedules if s.id == schedule_id), None)
        if schedule is None:
            click.echo(f"Error: Schedule '{schedule_id}' not found", err=True)
            sys.exit(1)

        # Generate occurrences
        engine = RecurrenceEngine()
        occurrences = engine.generate(schedule, start, end)

        # Print results
        click.echo(f"Schedule: {schedule.id}")
        click.echo(f"Frequency: {schedule.recurrence.frequency.value}")
        click.echo(f"Period: {start} to {end}")
        click.echo(f"\nExpected occurrences ({len(occurrences)}):")

        for occurrence_date in sorted(occurrences):
            click.echo(f"  {occurrence_date}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        sys.exit(1)


@main.command()
@click.argument("schedule_id")
@click.option(
    "--count",
    type=int,
    default=5,
    help="Number of future occurrences to show (default: 5)",
)
@click.option(
    "--from",
    "from_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Start date for occurrences (YYYY-MM-DD format)",
)
@click.option(
    "--to",
    "to_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="End date for occurrences (YYYY-MM-DD format)",
)
@click.option(
    "--schedules-path",
    type=click.Path(exists=True),
    default="schedules",
    help="Path to schedules file or directory (default: schedules)",
)
def show(
    schedule_id: str,
    count: int,
    from_date,
    to_date,
    schedules_path: str,
):
    """Show detailed information about a specific schedule.

    SCHEDULE_ID: The ID of the schedule to display

    Examples:
        beanschedule show mortgage-payment
        beanschedule show mortgage-payment --count 10
        beanschedule show mortgage-payment --from 2024-01-01 --to 2024-12-31
    """
    path_obj = Path(schedules_path)

    try:
        # Load schedules
        if path_obj.is_file():
            schedule_file = load_schedules_file(path_obj)
        elif path_obj.is_dir():
            schedule_file = load_schedules_from_directory(path_obj)
        else:
            click.echo(f"Error: Path not found: {path_obj}", err=True)
            sys.exit(1)

        if schedule_file is None:
            click.echo("Error: No schedules loaded", err=True)
            sys.exit(1)

        # Find schedule by ID
        schedule = next(
            (s for s in schedule_file.schedules if s.id == schedule_id),
            None,
        )
        if schedule is None:
            click.echo(f"Error: Schedule '{schedule_id}' not found", err=True)
            sys.exit(1)

        # Determine date range for occurrences
        if from_date is None:
            from_date = date.today()
        else:
            from_date = from_date.date()

        if to_date is None:
            # Calculate end date based on count and frequency
            # Use a generous range: at least count months into the future
            to_date = from_date + timedelta(days=count * 45)
        else:
            to_date = to_date.date()

        # Generate occurrences
        engine = RecurrenceEngine()
        occurrences = engine.generate(schedule, from_date, to_date)

        # Display schedule information
        status = "✓ enabled" if schedule.enabled else "✗ disabled"
        click.echo(f"Schedule: {schedule.id}")
        click.echo(f"Status: {status}")
        click.echo(f"Frequency: {schedule.recurrence.frequency.value}")

        # Show recurrence details
        rule = schedule.recurrence
        if rule.frequency.value == "WEEKLY" and rule.day_of_week:
            click.echo(f"Day: {rule.day_of_week.value}")
            if rule.interval and rule.interval > 1:
                click.echo(f"Interval: Every {rule.interval} weeks")
        elif rule.frequency.value == "MONTHLY" and rule.day_of_month:
            click.echo(f"Day of month: {rule.day_of_month}")
        elif rule.frequency.value == "YEARLY" and rule.month:
            click.echo(f"Month: {rule.month}")
            if rule.day_of_month:
                click.echo(f"Day: {rule.day_of_month}")
        elif rule.frequency.value == "BI_MONTHLY" and rule.days_of_month:
            click.echo(f"Days: {rule.days_of_month}")

        click.echo(f"Start date: {rule.start_date}")
        if rule.end_date:
            click.echo(f"End date: {rule.end_date}")

        # Match criteria
        click.echo("\nMatch Criteria:")
        click.echo(f"  Account: {schedule.match.account}")
        click.echo(f"  Payee pattern: {schedule.match.payee_pattern}")

        if schedule.match.amount:
            tolerance_str = ""
            if schedule.match.amount_tolerance is not None:
                tolerance_str = f" (± {schedule.match.amount_tolerance})"
            click.echo(f"  Amount: {schedule.match.amount}{tolerance_str}")
        elif schedule.match.amount_min and schedule.match.amount_max:
            click.echo(
                f"  Amount range: {schedule.match.amount_min} to "
                f"{schedule.match.amount_max}"
            )
        else:
            click.echo("  Amount: (any amount)")

        if schedule.match.date_window_days:
            click.echo(f"  Date window: ± {schedule.match.date_window_days} days")

        # Transaction template
        click.echo("\nTransaction Template:")
        if schedule.transaction.payee:
            click.echo(f"  Payee: {schedule.transaction.payee}")
        if schedule.transaction.narration:
            click.echo(f"  Narration: {schedule.transaction.narration}")
        if schedule.transaction.tags:
            click.echo(f"  Tags: {schedule.transaction.tags}")

        # Next occurrences
        sorted_occurrences = sorted(occurrences)[:count]
        click.echo(f"\nNext {len(sorted_occurrences)} occurrences:")

        for occurrence_date in sorted_occurrences:
            click.echo(f"  {occurrence_date}")

        if len(occurrences) > count:
            click.echo(f"\n({len(occurrences) - count} more occurrences in range)")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        sys.exit(1)


def _serialize_value(value: Any) -> Any:
    """
    Recursively convert Pydantic model values to YAML-serializable types.

    Handles conversion of common Python types to JSON/YAML-safe equivalents:
    - Decimal → float
    - Enum → enum value
    - dict-like objects → plain dict (recursively)
    - iterables → list (recursively)

    Args:
        value: The value to serialize (from a Pydantic model dump).

    Returns:
        The value converted to a YAML-serializable type.
    """
    try:
        if value is None:
            return None
        if isinstance(
            value,
            (bool, int, float),
        ):  # Check bool before int since bool is subclass of int
            return value
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, (date, str)):
            return value
        if hasattr(value, "items"):  # Duck typing for dict-like objects
            return {k: _serialize_value(v) for k, v in value.items()}
        if hasattr(value, "__iter__"):  # Duck typing for iterables (but not str/dict)
            return [_serialize_value(item) for item in value]
        return value
    except Exception:
        # If serialization fails, just return the value as-is
        return str(value)


@main.command()
@click.argument("path", type=click.Path(), required=False, default="schedules")
def init(path: str):
    """Initialize a new schedules directory with example files.

    Creates a schedules/ directory with example schedule files that
    demonstrate different recurrence patterns and matching strategies.

    PATH: Directory to create (default: schedules)

    Examples:
        beanschedule init
        beanschedule init my-schedules/
    """
    output_path = Path(path)

    # Check if directory exists
    if output_path.exists():
        click.confirm(
            f"Directory already exists: {output_path}\nContinue and overwrite files?",
            abort=True,
        )
    else:
        output_path.mkdir(parents=True, exist_ok=True)

    # Create config file
    config_path = output_path / "_config.yaml"
    config_content = """# Global configuration for beanschedule
fuzzy_match_threshold: 0.80
default_date_window_days: 3
default_amount_tolerance_percent: 0.02
placeholder_flag: '!'
"""

    with config_path.open("w") as f:
        f.write(config_content)

    click.echo(f"Created: {config_path}")

    # Create example schedule
    example_path = output_path / "example-rent.yaml"
    example_content = """# Example monthly rent payment
id: example-rent
enabled: true
match:
  account: Assets:Bank:Checking
  payee_pattern: "Property Manager|Landlord"
  amount: -1500.00
  amount_tolerance: 0.00
  date_window_days: 2
recurrence:
  frequency: MONTHLY
  day_of_month: 1
  start_date: 2024-01-01
transaction:
  payee: Property Manager
  narration: Monthly Rent
  tags: []
  metadata:
    schedule_id: example-rent
  postings:
    - account: Assets:Bank:Checking
      amount: null
    - account: Expenses:Housing:Rent
      amount: null
missing_transaction:
  create_placeholder: true
  flag: '!'
  narration_prefix: '[MISSING]'
"""

    with example_path.open("w") as f:
        f.write(example_content)

    click.echo(f"Created: {example_path}")
    click.echo(f"\n✓ Initialized schedule directory: {output_path}")
    click.echo("\nNext steps:")
    click.echo("  1. Edit the example schedule file or create your own")
    click.echo("  2. Validate your schedules: beanschedule validate " + str(output_path))
    click.echo("  3. Integrate with beangulp: import beanschedule in your config.py")


if __name__ == "__main__":
    main()
