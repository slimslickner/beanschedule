"""Command-line interface for beanschedule."""

import csv
import json
import logging
import re
import sys
import traceback
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import click
import yaml
from beancount import loader as beancount_loader
from beancount.core import data

from . import __version__
from .loader import load_schedules_file, load_schedules_from_directory
from .recurrence import RecurrenceEngine
from .types import DayOfWeek, FrequencyType

logger = logging.getLogger(__name__)


def complete_schedule_id(ctx, _, incomplete):
    """Complete schedule IDs from the schedules path.

    Loads available schedule IDs and returns those matching the incomplete string.
    Falls back to default 'schedules' path if --schedules-path not yet parsed.
    Used for shell tab completion on schedule_id arguments.
    """
    # Try to get schedules-path from context, use default if not available or None
    schedules_path = ctx.params.get("schedules_path") or "schedules"
    path_obj = Path(schedules_path)

    try:
        # Load schedules silently for completion
        if path_obj.is_file():
            schedule_file = load_schedules_file(path_obj)
        elif path_obj.is_dir():
            schedule_file = load_schedules_from_directory(path_obj)
        else:
            return []

        if schedule_file is None:
            return []

        # Return matching schedule IDs, sorted
        schedule_ids = sorted([s.id for s in schedule_file.schedules])
        return [sid for sid in schedule_ids if sid.startswith(incomplete)]
    except Exception:
        # Silently fail - don't break completion
        return []


def slugify(text: str) -> str:
    """Convert text to valid schedule ID.

    Converts text to lowercase, removes special characters,
    replaces spaces with hyphens, and strips leading/trailing hyphens.

    Args:
        text: The text to slugify.

    Returns:
        A valid schedule ID string.
    """
    # Lowercase and replace spaces with hyphens
    slug = text.lower().replace(" ", "-")
    # Remove special characters, keep only alphanumeric and hyphens
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    # Remove leading/trailing hyphens and multiple consecutive hyphens
    slug = slug.strip("-")
    return re.sub(r"-+", "-", slug)


def day_of_week_from_date(d: date) -> DayOfWeek:
    """Get the DayOfWeek enum from a date.

    Args:
        d: The date to get day of week for.

    Returns:
        The corresponding DayOfWeek enum.
    """
    # Python weekday: 0=Monday, 6=Sunday
    # DayOfWeek enum: MON=0, TUE=1, ..., SUN=6
    day_index = d.weekday()
    days = [
        DayOfWeek.MON,
        DayOfWeek.TUE,
        DayOfWeek.WED,
        DayOfWeek.THU,
        DayOfWeek.FRI,
        DayOfWeek.SAT,
        DayOfWeek.SUN,
    ]
    return days[day_index]


def extract_transaction_details(txn: data.Transaction) -> dict[str, Any]:
    """Extract schedule-relevant details from a beancount transaction.

    Args:
        txn: The beancount Transaction to extract from.

    Returns:
        Dictionary with transaction details: date, payee, narration, account,
        amount, tags, and postings list.

    Raises:
        ValueError: If transaction has no postings.
    """
    if not txn.postings:
        raise ValueError("Transaction has no postings")

    first_posting = txn.postings[0]

    postings = []
    for posting in txn.postings:
        posting_dict = {
            "account": posting.account,
            "amount": float(posting.units.number) if posting.units else None,
            "narration": posting.meta.get("narration") if posting.meta else None,
        }
        postings.append(posting_dict)

    return {
        "date": txn.date,
        "payee": txn.payee,
        "narration": txn.narration,
        "account": first_posting.account,
        "amount": float(first_posting.units.number) if first_posting.units else None,
        "tags": list(txn.tags),
        "postings": postings,
    }


def build_schedule_dict(
    schedule_id: str,
    txn_details: dict[str, Any],
    payee_pattern: str,
    amount_tolerance: Decimal,
    date_window_days: int,
    frequency: FrequencyType,
    day_of_month: int | None = None,
    month: int | None = None,
    day_of_week: DayOfWeek | None = None,
    interval: int = 1,
    days_of_month: list[int] | None = None,
    interval_months: int | None = None,
) -> dict[str, Any]:
    """Build a complete schedule dictionary matching the Pydantic schema.

    Args:
        schedule_id: Unique schedule identifier.
        txn_details: Transaction details from extract_transaction_details().
        payee_pattern: Payee pattern for matching.
        amount_tolerance: Amount tolerance (±).
        date_window_days: Date matching window in days.
        frequency: Recurrence frequency type.
        day_of_month: Day of month for MONTHLY/YEARLY.
        month: Month for YEARLY.
        day_of_week: Day of week for WEEKLY.
        interval: Interval for WEEKLY (e.g., 2 for biweekly).
        days_of_month: Days of month for BIMONTHLY.
        interval_months: Month interval for INTERVAL.

    Returns:
        Dictionary representing a complete Schedule.
    """
    return {
        "id": schedule_id,
        "enabled": True,
        "match": {
            "account": txn_details["account"],
            "payee_pattern": payee_pattern,
            "amount": float(txn_details["amount"]) if txn_details["amount"] is not None else None,
            "amount_tolerance": float(amount_tolerance),
            "amount_min": None,
            "amount_max": None,
            "date_window_days": date_window_days,
        },
        "recurrence": {
            "frequency": frequency.value,
            "start_date": str(txn_details["date"]),
            "end_date": None,
            "day_of_month": day_of_month,
            "month": month,
            "day_of_week": day_of_week.value if day_of_week else None,
            "interval": interval,
            "days_of_month": days_of_month,
            "interval_months": interval_months,
        },
        "transaction": {
            "payee": txn_details["payee"],
            "narration": txn_details["narration"],
            "tags": txn_details["tags"],
            "metadata": {
                "schedule_id": schedule_id,
            },
            "postings": txn_details["postings"],
        },
        "missing_transaction": {
            "create_placeholder": True,
            "flag": "!",
            "narration_prefix": "[MISSING]",
        },
    }


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
@click.argument("schedule_id", shell_complete=complete_schedule_id)
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
@click.argument("schedule_id", shell_complete=complete_schedule_id)
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


@main.command()
@click.option(
    "--ledger",
    "-l",
    "ledger_path",
    type=click.Path(exists=True),
    required=True,
    help="Path to Beancount ledger file",
)
@click.option(
    "--date",
    "-d",
    "target_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    required=True,
    help="Transaction date (YYYY-MM-DD)",
)
@click.option(
    "--output",
    "-o",
    "output_path",
    type=click.Path(),
    default=None,
    help="Output file path (default: schedules/{id}.yaml)",
)
@click.option(
    "--schedules-dir",
    type=click.Path(),
    default="schedules",
    help="Schedules directory (default: schedules)",
)
def create(ledger_path: str, target_date, output_path: str | None, schedules_dir: str):
    """Create schedule YAML templates from existing ledger transactions.

    Loads a transaction from your ledger and guides you through creating
    a schedule template for it. The generated schedule will match future
    occurrences of similar transactions.

    Examples:
        beanschedule create --ledger ledger.bean --date 2024-01-15
        beanschedule create -l ledger.bean -d 2024-01-15 -o schedules/rent.yaml
    """
    try:
        # Load ledger file
        ledger_file = Path(ledger_path)
        click.echo(f"Loading ledger from: {ledger_file}")

        entries, errors, _ = beancount_loader.load_file(str(ledger_file))

        if errors:
            click.echo("Errors found while loading ledger:", err=True)
            for error in errors:
                click.echo(f"  {error}", err=True)
            sys.exit(1)

        # Filter transactions by date
        target = target_date.date()
        transactions = [
            e for e in entries
            if isinstance(e, data.Transaction) and e.date == target
        ]

        if not transactions:
            click.echo(f"No transactions found on {target}", err=True)
            msg = "Tip: Check the date format (YYYY-MM-DD) and try another date"
            click.echo(msg, err=True)
            sys.exit(1)

        # Select transaction if multiple
        if len(transactions) > 1:
            click.echo(f"\nFound {len(transactions)} transactions on {target}:")
            for i, txn in enumerate(transactions, 1):
                first_posting = txn.postings[0] if txn.postings else None
                amount_str = (
                    f"{first_posting.units}"
                    if first_posting and first_posting.units
                    else "?"
                )
                account_str = (
                    first_posting.account if first_posting else "?"
                )
                click.echo(
                    f"  {i}. {txn.payee or '(no payee)':<25} "
                    f"{txn.narration:<20} {account_str:<30} {amount_str}",
                )

            # Prompt for selection
            selection = click.prompt(
                "Select transaction number",
                type=click.IntRange(1, len(transactions)),
            )
            txn = transactions[selection - 1]
        else:
            txn = transactions[0]
            click.echo("\nSelected transaction:")
            first_posting = txn.postings[0] if txn.postings else None
            if first_posting:
                click.echo(f"  Payee: {txn.payee}")
                click.echo(f"  Narration: {txn.narration}")
                click.echo(f"  Account: {first_posting.account}")
                click.echo(f"  Amount: {first_posting.units}")

        # Extract transaction details
        try:
            txn_details = extract_transaction_details(txn)
        except ValueError as e:
            click.echo(f"Error extracting transaction details: {e}", err=True)
            sys.exit(1)

        click.echo("")

        # Prompt for schedule ID
        default_schedule_id = slugify(txn.payee or "transaction")
        schedule_id = click.prompt(
            "Schedule ID",
            default=default_schedule_id,
            type=str,
        )
        # Slugify the user input
        schedule_id = slugify(schedule_id)

        # Prompt for recurrence frequency
        click.echo("\nRecurrence frequency:")
        frequency_options = {
            "1": ("MONTHLY", FrequencyType.MONTHLY),
            "2": ("WEEKLY", FrequencyType.WEEKLY),
            "3": ("YEARLY", FrequencyType.YEARLY),
            "4": ("INTERVAL", FrequencyType.INTERVAL),
            "5": ("BIMONTHLY", FrequencyType.BIMONTHLY),
        }
        for key, (label, _) in frequency_options.items():
            click.echo(f"  {key}. {label}")

        freq_choice = click.prompt(
            "Select frequency",
            type=click.Choice(list(frequency_options.keys())),
        )
        _, frequency = frequency_options[freq_choice]

        # Collect frequency-specific details
        day_of_month = None
        month = None
        day_of_week = None
        interval = 1
        days_of_month = None
        interval_months = None

        if frequency == FrequencyType.MONTHLY:
            day_of_month = click.prompt(
                "Day of month (1-31)",
                default=txn.date.day,
                type=click.IntRange(1, 31),
            )
        elif frequency == FrequencyType.WEEKLY:
            day_of_week = day_of_week_from_date(txn.date)
            click.echo(f"Day of week: {day_of_week.value}")
            interval = click.prompt(
                "Interval (1=weekly, 2=biweekly, etc.)",
                default=1,
                type=click.IntRange(1, 52),
            )
        elif frequency == FrequencyType.YEARLY:
            month = click.prompt(
                "Month (1-12)",
                default=txn.date.month,
                type=click.IntRange(1, 12),
            )
            day_of_month = click.prompt(
                "Day of month (1-31)",
                default=txn.date.day,
                type=click.IntRange(1, 31),
            )
        elif frequency == FrequencyType.INTERVAL:
            interval_months = click.prompt(
                "Month interval (e.g., 3 for quarterly)",
                default=1,
                type=click.IntRange(1, 24),
            )
            day_of_month = click.prompt(
                "Day of month (1-31)",
                default=txn.date.day,
                type=click.IntRange(1, 31),
            )
        elif frequency == FrequencyType.BIMONTHLY:
            days_input = click.prompt(
                "Days of month (comma-separated, e.g., 1,15)",
                default=f"{txn.date.day}",
            )
            try:
                days_of_month = [int(d.strip()) for d in days_input.split(",")]
                # Validate (1-31 valid days of month)
                max_day = 31
                min_day = 1
                for d in days_of_month:
                    if d < min_day or d > max_day:
                        raise ValueError(f"Day {d} out of range")
            except ValueError as e:
                click.echo(f"Error parsing days: {e}", err=True)
                sys.exit(1)

        # Prompt for match criteria
        click.echo("\nMatch Criteria:")
        tolerance_str = click.prompt(
            "Amount tolerance (0 for exact match)",
            default="0.00",
            type=str,
        )
        amount_tolerance = Decimal(tolerance_str)
        date_window_days = click.prompt(
            "Date window in days (±)",
            default=3,
            type=click.IntRange(0, 31),
        )

        # Payee pattern
        payee_pattern = click.prompt(
            "Payee pattern (regex or literal text)",
            default=txn.payee or "",
        )

        # Build schedule dictionary
        schedule_dict = build_schedule_dict(
            schedule_id=schedule_id,
            txn_details=txn_details,
            payee_pattern=payee_pattern,
            amount_tolerance=amount_tolerance,
            date_window_days=date_window_days,
            frequency=frequency,
            day_of_month=day_of_month,
            month=month,
            day_of_week=day_of_week,
            interval=interval,
            days_of_month=days_of_month,
            interval_months=interval_months,
        )

        # Display YAML preview
        click.echo("\n--- Generated Schedule ---")
        yaml_content = yaml.dump(
            schedule_dict,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        click.echo(yaml_content)

        # Confirm save
        if not click.confirm("Save schedule?"):
            click.echo("Cancelled.")
            return

        # Determine output file (filename must match schedule ID for directory mode)
        if output_path is None:
            output_file = Path(schedules_dir) / f"{schedule_id}.yaml"
        else:
            # When output path is specified, ensure filename matches schedule ID
            # This is required for the loader to find the schedule in directory mode
            output_dir = Path(output_path).parent
            output_file = output_dir / f"{schedule_id}.yaml"

        # Create parent directory if needed
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Check if file exists
        if output_file.exists() and not click.confirm(
            f"File exists: {output_file}\nOverwrite?",
        ):
            click.echo("Cancelled.")
            return

        # Write YAML file
        with output_file.open("w") as f:
            # Write header comment
            f.write(f"# Schedule created from transaction on {txn.date}\n")
            f.write(f"# Payee: {txn.payee}\n")
            f.write(f"# Narration: {txn.narration}\n\n")
            # Write schedule
            f.write(yaml_content)

        click.echo(f"✓ Schedule saved to: {output_file}")
        click.echo("\nNext steps:")
        click.echo(f"  1. Validate: beanschedule validate {schedules_dir}/")
        click.echo(
            f"  2. Review: beanschedule show {schedule_id} "
            f"--schedules-path {schedules_dir}/",
        )
        msg = "3. Customize the schedule as needed (payee pattern, amounts, etc.)"
        click.echo(f"  {msg}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        sys.exit(1)


@main.command()
@click.argument("ledger_path", type=click.Path(exists=True))
@click.option(
    "--confidence",
    type=float,
    default=0.60,
    help="Minimum confidence threshold (0.0-1.0, default: 0.60)",
)
@click.option(
    "--fuzzy-threshold",
    type=float,
    default=0.85,
    help="Payee fuzzy match threshold (0.0-1.0, default: 0.85)",
)
@click.option(
    "--amount-tolerance",
    type=float,
    default=0.05,
    help="Amount variance tolerance as percentage (default: 0.05 = 5%)",
)
@click.option(
    "--min-occurrences",
    type=int,
    default=3,
    help="Minimum transaction occurrences to detect pattern (default: 3)",
)
@click.option(
    "--output-dir",
    type=click.Path(),
    default=None,
    help="Save detected schedules as YAML files to this directory",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format (default: table)",
)
def detect(
    ledger_path: str,
    confidence: float,
    fuzzy_threshold: float,
    amount_tolerance: float,
    min_occurrences: int,
    output_dir: str | None,
    output_format: str,
):
    """Detect recurring transaction patterns in a ledger.

    Analyzes your Beancount ledger to discover recurring transactions
    and generates schedule templates with confidence scoring.

    Examples:
        beanschedule detect ledger.bean
        beanschedule detect ledger.bean --confidence 0.75
        beanschedule detect ledger.bean --output-dir detected-schedules/
        beanschedule detect ledger.bean --format json
    """
    from .detector import RecurrenceDetector

    try:
        # Validate input parameters
        if not (0.0 <= confidence <= 1.0):
            click.echo("Error: --confidence must be between 0.0 and 1.0", err=True)
            sys.exit(1)

        if not (0.0 <= fuzzy_threshold <= 1.0):
            click.echo("Error: --fuzzy-threshold must be between 0.0 and 1.0", err=True)
            sys.exit(1)

        if not (0.0 <= amount_tolerance <= 1.0):
            click.echo("Error: --amount-tolerance must be between 0.0 and 1.0", err=True)
            sys.exit(1)

        if min_occurrences < 2:
            click.echo("Error: --min-occurrences must be at least 2", err=True)
            sys.exit(1)

        # Load ledger
        ledger_file = Path(ledger_path)
        click.echo(f"Loading ledger from: {ledger_file}")

        entries, errors, _ = beancount_loader.load_file(str(ledger_file))

        if errors:
            click.echo("Errors found while loading ledger:", err=True)
            for error in errors:
                click.echo(f"  {error}", err=True)
            sys.exit(1)

        # Create detector and run detection
        detector = RecurrenceDetector(
            fuzzy_threshold=fuzzy_threshold,
            amount_tolerance_pct=amount_tolerance,
            min_occurrences=min_occurrences,
            min_confidence=confidence,
        )

        click.echo(f"Analyzing {len(entries)} ledger entries...")
        candidates = detector.detect(entries)

        if not candidates:
            click.echo("No recurring patterns detected.")
            click.echo(
                f"Try adjusting thresholds: lower --confidence or "
                f"--min-occurrences"
            )
            sys.exit(0)

        # Display results
        click.echo(f"\nDetected {len(candidates)} recurring patterns:\n")

        if output_format == "table":
            _print_detection_table(candidates)
        elif output_format == "json":
            _print_detection_json(candidates)

        # Show top candidates with schedule creation guidance
        if output_format == "table":
            click.echo(f"\n{'─' * 120}")
            click.echo("\nTo manually create schedules for detected patterns, use `beanschedule create`:")
            click.echo("Examples for top patterns:\n")
            for candidate in candidates[:3]:
                cmd = (
                    f"  beanschedule create --ledger {ledger_path} "
                    f"--date {candidate.first_date}"
                )
                click.echo(f"  {candidate.confidence*100:.0f}% confidence - {candidate.payee}")
                click.echo(f"  {cmd}")
                click.echo()

        # Save to YAML files if requested
        if output_dir:
            output_path = Path(output_dir)
            saved_count = _save_detected_schedules(candidates, output_path)
            click.echo(f"\n✓ Saved {saved_count} schedules to: {output_path}")
            click.echo("\nNext steps:")
            click.echo(f"  1. Review: beanschedule list {output_path}")
            click.echo(f"  2. Validate: beanschedule validate {output_path}")
            click.echo(f"  3. Customize as needed (payee patterns, amounts, etc.)")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        sys.exit(1)


def _print_detection_table(candidates: list) -> None:
    """Print detected patterns as a formatted ASCII table.

    Shows confidence, frequency, payee, account, amount, and transaction count
    for each detected pattern. Displays full account names without truncation.

    Args:
        candidates: List of RecurringCandidate objects.
    """
    # Calculate column widths (no hard cap on account width)
    confidence_width = len("Confidence")
    frequency_width = max(
        len("Frequency"),
        max((len(c.frequency.formatted_name()) for c in candidates), default=0),
    )
    frequency_width = min(frequency_width, 15)

    payee_width = max(
        len("Payee"),
        max((len(c.payee) for c in candidates), default=0),
    )
    payee_width = min(payee_width, 25)

    # Calculate account width dynamically without hard cap
    account_width = max(
        len("Account"),
        max((len(c.account) for c in candidates), default=0),
    )

    amount_width = len("Amount")

    # Print header
    header = (
        f"{'Confidence':<{confidence_width}}  "
        f"{'Frequency':<{frequency_width}}  "
        f"{'Payee':<{payee_width}}  "
        f"{'Account':<{account_width}}  "
        f"{'Amount':<{amount_width}}  "
        f"Count"
    )
    click.echo(header)
    click.echo("-" * min(len(header), 120))  # Cap separator line at 120 chars

    # Print candidates sorted by confidence (highest first)
    for candidate in candidates:
        confidence_pct = f"{candidate.confidence * 100:.0f}%"
        frequency_name = candidate.frequency.formatted_name()
        payee = candidate.payee[:payee_width]
        account = candidate.account  # No truncation
        amount = f"{candidate.amount:.2f}"

        row = (
            f"{confidence_pct:<{confidence_width}}  "
            f"{frequency_name:<{frequency_width}}  "
            f"{payee:<{payee_width}}  "
            f"{account:<{account_width}}  "
            f"{amount:<{amount_width}}  "
            f"{candidate.transaction_count}"
        )
        click.echo(row)


def _print_detection_json(candidates: list) -> None:
    """Print detected patterns as JSON.

    Args:
        candidates: List of RecurringCandidate objects.
    """
    output = []
    for c in candidates:
        output.append(
            {
                "schedule_id": c.schedule_id,
                "payee": c.payee,
                "account": c.account,
                "amount": float(c.amount),
                "amount_tolerance": float(c.amount_tolerance),
                "frequency": c.frequency.frequency.value,
                "frequency_name": c.frequency.formatted_name(),
                "confidence": round(c.confidence, 3),
                "transaction_count": c.transaction_count,
                "date_range": {
                    "first": str(c.first_date),
                    "last": str(c.last_date),
                },
                "expected_occurrences": c.expected_occurrences,
            }
        )

    click.echo(json.dumps(output, indent=2))


def _save_detected_schedules(candidates: list, output_dir: Path) -> int:
    """Save detected candidates as YAML schedule files.

    Creates a schedules directory with individual YAML files for each
    detected pattern, ready to be customized and used.

    Args:
        candidates: List of RecurringCandidate objects.
        output_dir: Directory to save schedule files.

    Returns:
        Number of schedules saved.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create _config.yaml if it doesn't exist
    config_file = output_dir / "_config.yaml"
    if not config_file.exists():
        config = {
            "fuzzy_match_threshold": 0.80,
            "default_date_window_days": 3,
            "default_amount_tolerance_percent": 0.02,
            "placeholder_flag": "!",
        }
        with config_file.open("w") as f:
            yaml.dump(config, f)

    saved_count = 0

    for candidate in candidates:
        # Build schedule dictionary
        schedule_dict = {
            "id": candidate.schedule_id,
            "enabled": True,
            "match": {
                "account": candidate.account,
                "payee_pattern": candidate.payee_pattern,
                "amount": float(candidate.amount),
                "amount_tolerance": float(candidate.amount_tolerance),
                "amount_min": None,
                "amount_max": None,
                "date_window_days": 3,
            },
            "recurrence": {
                "frequency": candidate.frequency.frequency.value,
                "start_date": str(candidate.first_date),
                "end_date": None,
                "day_of_month": candidate.frequency.day_of_month,
                "month": candidate.frequency.month,
                "day_of_week": (
                    candidate.frequency.day_of_week.value
                    if candidate.frequency.day_of_week
                    else None
                ),
                "interval": candidate.frequency.interval,
                "days_of_month": None,
                "interval_months": candidate.frequency.interval_months,
            },
            "transaction": {
                "payee": candidate.payee,
                "narration": f"{candidate.frequency.formatted_name()} transaction",
                "tags": [],
                "metadata": {
                    "schedule_id": candidate.schedule_id,
                },
                "postings": None,
            },
            "missing_transaction": {
                "create_placeholder": True,
                "flag": "!",
                "narration_prefix": "[MISSING]",
            },
        }

        # Write YAML file
        output_file = output_dir / f"{candidate.schedule_id}.yaml"
        with output_file.open("w") as f:
            f.write(f"# Auto-detected {candidate.frequency.formatted_name()} pattern\n")
            f.write(
                f"# Confidence: {candidate.confidence * 100:.0f}% "
                f"({candidate.transaction_count} transactions)\n"
            )
            f.write(f"# Date range: {candidate.first_date} to {candidate.last_date}\n")
            f.write(f"# Payee: {candidate.payee}\n\n")
            yaml.dump(
                schedule_dict,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        saved_count += 1
        logger.info("Saved schedule: %s", output_file)

    return saved_count


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


@main.command()
@click.argument("yaml_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Output file (default: stdout)")
@click.option(
    "--group-by",
    type=click.Choice(["none", "frequency", "account"]),
    default="none",
    help="Group schedules in output",
)
def migrate(yaml_path: str, output: str | None, group_by: str):
    """Migrate YAML schedules to forecast transaction format.

    Converts schedules.yaml or schedules/ directory to Forecast.bean format
    using # flagged transactions with schedule-* metadata.

    Args:
        YAML_PATH: Path to schedules.yaml file or schedules/ directory

    Examples:
        beanschedule migrate schedules.yaml
        beanschedule migrate schedules.yaml -o Forecast.bean
        beanschedule migrate schedules/ --group-by frequency
    """
    from beancount.core import amount as beancount_amount
    from beancount.core import data as beancount_data
    from beancount.parser import printer

    from .loader import load_schedules_file, load_schedules_from_directory

    # Load YAML schedules
    yaml_path_obj = Path(yaml_path)
    click.echo(f"Loading schedules from: {yaml_path_obj}")

    try:
        if yaml_path_obj.is_file():
            schedule_file = load_schedules_file(yaml_path_obj)
        elif yaml_path_obj.is_dir():
            schedule_file = load_schedules_from_directory(yaml_path_obj)
        else:
            click.echo(f"Error: Invalid path: {yaml_path}", err=True)
            sys.exit(1)

        if schedule_file is None:
            click.echo("Error: Failed to load schedules", err=True)
            sys.exit(1)

    except Exception as e:
        click.echo(f"Error loading schedules: {e}", err=True)
        sys.exit(1)

    if not schedule_file.schedules:
        click.echo("Warning: No schedules found in file", err=True)
        sys.exit(1)

    click.echo(f"Found {len(schedule_file.schedules)} schedule(s)")

    # Group schedules if requested
    if group_by == "frequency":
        schedules_grouped = {}
        for schedule in schedule_file.schedules:
            freq = schedule.recurrence.frequency.value
            if freq not in schedules_grouped:
                schedules_grouped[freq] = []
            schedules_grouped[freq].append(schedule)
        groups = list(schedules_grouped.items())
    elif group_by == "account":
        schedules_grouped = {}
        for schedule in schedule_file.schedules:
            account = schedule.match.account
            if account not in schedules_grouped:
                schedules_grouped[account] = []
            schedules_grouped[account].append(schedule)
        groups = list(schedules_grouped.items())
    else:
        # No grouping
        groups = [("all", schedule_file.schedules)]

    # Convert schedules to forecast transactions
    all_entries = []

    for group_name, schedules in groups:
        if group_by != "none":
            # Add comment header for group
            all_entries.append("")  # Blank line
            all_entries.append(f"; === {group_name.upper()} ===")
            all_entries.append("")

        for schedule in schedules:
            forecast_txn = _schedule_to_forecast_transaction(schedule)
            all_entries.append(forecast_txn)

    # Format output
    output_lines = []
    output_lines.append("; Forecast transactions generated by beanschedule migrate")
    output_lines.append(f"; Source: {yaml_path}")
    output_lines.append(f"; Generated: {date.today().isoformat()}")
    output_lines.append("")
    output_lines.append("; Include this file in your main ledger:")
    output_lines.append(";   include \"Forecast.bean\"")
    output_lines.append("")

    for entry in all_entries:
        if isinstance(entry, str):
            # Comment or blank line
            output_lines.append(entry)
        else:
            # Transaction - format with printer
            output_lines.append(printer.format_entry(entry))

    output_text = "\n".join(output_lines)

    # Write output
    if output:
        output_path = Path(output)
        with open(output_path, "w") as f:
            f.write(output_text)
        click.echo(f"\n✓ Wrote {len(schedule_file.schedules)} forecast transaction(s) to {output_path}")
    else:
        click.echo("\n" + output_text)

    click.echo(f"\nNext steps:")
    click.echo("  1. Review the generated forecast transactions")
    click.echo("  2. Include Forecast.bean in your main ledger")
    click.echo("  3. Run: bean-check main.beancount")
    click.echo("  4. Start using: bean-extract config.py bank.csv")


def _build_forecast_pattern(schedule) -> str:
    """
    Build forecast pattern string for transaction narration.

    Supports beanlabs-compatible patterns for basic frequencies (MONTHLY, WEEKLY, YEARLY)
    and extended patterns for advanced recurrence (MONTHLY_ON_DAYS, NTH_WEEKDAY, etc.).

    Args:
        schedule: Schedule object with recurrence rules

    Returns:
        Forecast pattern string like "[MONTHLY]", "[MONTHLY ON 5,20]", "[2ND TUE]", etc.
    """
    freq = schedule.recurrence.frequency.value
    pattern_parts = []

    # Map frequency to pattern
    if freq == "MONTHLY":
        pattern_parts.append("MONTHLY")
    elif freq == "WEEKLY":
        pattern_parts.append("WEEKLY")
    elif freq == "YEARLY":
        pattern_parts.append("YEARLY")
    elif freq == "DAILY":
        pattern_parts.append("DAILY")
    elif freq == "MONTHLY_ON_DAYS":
        # Extended syntax: [MONTHLY ON 5,20]
        if schedule.recurrence.days_of_month:
            days_str = ",".join(str(d) for d in schedule.recurrence.days_of_month)
            pattern_parts.append(f"MONTHLY ON {days_str}")
        else:
            pattern_parts.append("MONTHLY")
    elif freq == "NTH_WEEKDAY":
        # Extended syntax: [2ND TUE], [LAST FRI]
        nth = schedule.recurrence.nth_occurrence
        day = schedule.recurrence.day_of_week.value if schedule.recurrence.day_of_week else "MON"

        if nth == -1:
            pattern_parts.append(f"LAST {day}")
        elif nth == 1:
            pattern_parts.append(f"1ST {day}")
        elif nth == 2:
            pattern_parts.append(f"2ND {day}")
        elif nth == 3:
            pattern_parts.append(f"3RD {day}")
        else:
            pattern_parts.append(f"{nth}TH {day}")
    elif freq == "LAST_DAY_OF_MONTH":
        # Extended syntax: [LAST DAY OF MONTH]
        pattern_parts.append("LAST DAY OF MONTH")
    elif freq == "INTERVAL":
        # Extended syntax: [EVERY 3 MONTHS]
        if schedule.recurrence.interval_months:
            pattern_parts.append(f"EVERY {schedule.recurrence.interval_months} MONTHS")
        else:
            pattern_parts.append("MONTHLY")
    elif freq == "BIMONTHLY":
        # Extended syntax: [BIMONTHLY ON 5,20]
        if schedule.recurrence.days_of_month:
            days_str = ",".join(str(d) for d in schedule.recurrence.days_of_month)
            pattern_parts.append(f"BIMONTHLY ON {days_str}")
        else:
            pattern_parts.append("BIMONTHLY")
    else:
        # Fallback to frequency name
        pattern_parts.append(freq)

    # Add UNTIL condition if end_date specified
    if schedule.recurrence.end_date:
        pattern_parts.append(f"UNTIL {schedule.recurrence.end_date.isoformat()}")

    return "[" + " ".join(pattern_parts) + "]"


def _schedule_to_forecast_transaction(schedule) -> data.Transaction:
    """
    Convert a YAML Schedule to a forecast transaction.

    Args:
        schedule: Schedule object from YAML

    Returns:
        Transaction with # flag and schedule-* metadata
    """
    from beancount.core import amount as beancount_amount
    from beancount.core import data as beancount_data
    from decimal import Decimal

    # Build metadata from schedule
    meta = {
        "schedule-id": schedule.id,
        "schedule-frequency": schedule.recurrence.frequency.value,
        "schedule-match-account": schedule.match.account,
    }

    # Add match criteria
    if schedule.match.payee_pattern != ".*":
        meta["schedule-payee-pattern"] = schedule.match.payee_pattern

    if schedule.match.amount is not None:
        meta["schedule-amount"] = str(schedule.match.amount)

    if schedule.match.amount_tolerance is not None:
        meta["schedule-amount-tolerance"] = str(schedule.match.amount_tolerance)

    if schedule.match.amount_min is not None:
        meta["schedule-amount-min"] = str(schedule.match.amount_min)

    if schedule.match.amount_max is not None:
        meta["schedule-amount-max"] = str(schedule.match.amount_max)

    if schedule.match.date_window_days and schedule.match.date_window_days != 3:
        meta["schedule-date-window-days"] = str(schedule.match.date_window_days)

    # Add recurrence fields based on frequency
    if schedule.recurrence.frequency.value == "MONTHLY":
        if schedule.recurrence.day_of_month:
            meta["schedule-day-of-month"] = str(schedule.recurrence.day_of_month)

    elif schedule.recurrence.frequency.value == "WEEKLY":
        if schedule.recurrence.day_of_week:
            meta["schedule-day-of-week"] = schedule.recurrence.day_of_week.value
        if schedule.recurrence.interval and schedule.recurrence.interval != 1:
            meta["schedule-interval"] = str(schedule.recurrence.interval)

    elif schedule.recurrence.frequency.value == "YEARLY":
        if schedule.recurrence.month:
            meta["schedule-month"] = str(schedule.recurrence.month)
        if schedule.recurrence.day_of_month:
            meta["schedule-day-of-month"] = str(schedule.recurrence.day_of_month)

    elif schedule.recurrence.frequency.value == "INTERVAL":
        if schedule.recurrence.interval_months:
            meta["schedule-interval-months"] = str(schedule.recurrence.interval_months)
        if schedule.recurrence.day_of_month:
            meta["schedule-day-of-month"] = str(schedule.recurrence.day_of_month)

    elif schedule.recurrence.frequency.value in ("BIMONTHLY", "MONTHLY_ON_DAYS"):
        if schedule.recurrence.days_of_month:
            meta["schedule-days-of-month"] = ",".join(
                str(d) for d in schedule.recurrence.days_of_month
            )

    elif schedule.recurrence.frequency.value == "NTH_WEEKDAY":
        if schedule.recurrence.nth_occurrence:
            meta["schedule-nth-occurrence"] = str(schedule.recurrence.nth_occurrence)
        if schedule.recurrence.day_of_week:
            meta["schedule-day-of-week"] = schedule.recurrence.day_of_week.value

    # Add end date if specified
    if schedule.recurrence.end_date:
        meta["schedule-until"] = schedule.recurrence.end_date.isoformat()

    # Add enabled flag if disabled
    if not schedule.enabled:
        meta["schedule-enabled"] = "false"

    # Add placeholder config if non-default
    if not schedule.missing_transaction.create_placeholder:
        meta["schedule-placeholder-enabled"] = "false"
    if schedule.missing_transaction.flag != "!":
        meta["schedule-placeholder-flag"] = schedule.missing_transaction.flag
    if schedule.missing_transaction.narration_prefix != "[MISSING]":
        meta["schedule-placeholder-narration-prefix"] = schedule.missing_transaction.narration_prefix

    # Build postings - match account uses match.amount, others only if specified
    postings = []
    if schedule.transaction.postings:
        match_account = schedule.match.account
        # Use match.amount for the match account posting
        match_amount = Decimal(str(schedule.match.amount)) if schedule.match.amount is not None else None

        for posting_template in schedule.transaction.postings:
            is_match_account = posting_template.account == match_account

            # Determine amount for this posting
            if is_match_account and match_amount is not None:
                # Match account: use match.amount from schedule
                amount = match_amount
            elif posting_template.amount is not None:
                # Other accounts: use amount from template if specified
                amount = Decimal(str(posting_template.amount))
            else:
                # No amount specified: leave as None for auto-balancing
                amount = None

            posting_meta = {}
            if posting_template.narration:
                posting_meta["narration"] = posting_template.narration

            # Only create Amount object if amount is specified
            units = beancount_amount.Amount(amount, "USD") if amount is not None else None

            posting = beancount_data.Posting(
                account=posting_template.account,
                units=units,
                cost=None,
                price=None,
                flag=None,
                meta=posting_meta if posting_meta else None,
            )
            postings.append(posting)

    # Build narration with forecast pattern
    base_narration = schedule.transaction.narration or ""
    forecast_pattern = _build_forecast_pattern(schedule)

    # Combine: "Description [PATTERN]" or just "[PATTERN]" if no description
    if base_narration:
        full_narration = f"{base_narration} {forecast_pattern}"
    else:
        full_narration = forecast_pattern

    # Calculate appropriate forecast date (next occurrence from today)
    from datetime import date as date_type
    from .recurrence import RecurrenceEngine

    today = date_type.today()
    engine = RecurrenceEngine()

    # Generate next occurrence from today
    # Use start_date as the beginning of the window
    window_start = min(schedule.recurrence.start_date, today)
    window_end = today + timedelta(days=365)

    occurrences = engine.generate(schedule, window_start, window_end)

    # Find first occurrence >= today
    future_occurrences = [d for d in occurrences if d >= today]

    if future_occurrences:
        forecast_date = future_occurrences[0]
    else:
        # No future occurrences, use start_date as fallback
        forecast_date = schedule.recurrence.start_date

    # Build transaction
    txn = beancount_data.Transaction(
        meta=meta,
        date=forecast_date,
        flag="#",
        payee=schedule.transaction.payee or "",
        narration=full_narration,
        tags=frozenset(schedule.transaction.tags) if schedule.transaction.tags else frozenset(),
        links=frozenset(),
        postings=postings,
    )

    return txn


@main.command()
@click.argument("ledger_file", required=False, type=click.Path(exists=True))
@click.option("--forecast-file", "-f", type=click.Path(exists=True), help="Forecast file to update")
@click.option("--dry-run", is_flag=True, help="Preview changes without writing")
def advance_forecasts(ledger_file: str | None, forecast_file: str | None, dry_run: bool):
    """Advance matched forecast transactions to their next occurrence.

    Queries the ledger for matched transactions and updates forecast dates
    to the next occurrence.

    Args:
        LEDGER_FILE: Path to main ledger file (default: $BEANSCHEDULE_LEDGER_FILE or main.beancount)

    Options:
        --forecast-file: Forecast file to update (default: Forecast.bean)
        --dry-run: Preview changes without writing

    Examples:
        beanschedule advance-forecasts
        beanschedule advance-forecasts main.beancount
        beanschedule advance-forecasts --forecast-file Forecast.bean --dry-run
        BEANSCHEDULE_LEDGER_FILE=ledger.bean beanschedule advance-forecasts
    """
    import os
    from collections import defaultdict

    from beancount import loader
    from beancount.parser import printer

    from .forecast_advancement import advance_forecast_transaction
    from .forecast_loader import load_forecast_schedules

    # 1. Determine ledger file path
    if not ledger_file:
        ledger_file = os.getenv("BEANSCHEDULE_LEDGER_FILE", "main.beancount")

    ledger_path = Path(ledger_file)
    if not ledger_path.exists():
        click.echo(f"Error: Ledger file not found: {ledger_path}", err=True)
        sys.exit(1)

    click.echo(f"Loading ledger: {ledger_path}")

    # 2. Load ledger (includes Forecast.bean)
    entries, errors, options_map = loader.load_file(str(ledger_path))

    if errors:
        click.echo(f"Warning: {len(errors)} error(s) loading ledger", err=True)
        for error in errors[:5]:
            click.echo(f"  {error}", err=True)

    # 3. Find matched transactions (schedule_id metadata) in the ledger
    # We'll find forecast transactions later from the Forecast.bean file
    matched_by_schedule = defaultdict(list)  # schedule_id -> [matched transactions]

    for entry in entries:
        if not isinstance(entry, data.Transaction):
            continue

        # Matched transactions have schedule_id metadata (from hook)
        # IMPORTANT: Ignore forecast-generated transactions (flag == '#')
        # Only real transactions (flag == '*' or '!') should be considered matches
        if "schedule_id" in entry.meta and entry.flag != "#":
            schedule_id = entry.meta["schedule_id"]
            matched_by_schedule[schedule_id].append(entry)

    if not matched_by_schedule:
        click.echo("No matched forecasts found in ledger")
        return

    click.echo(f"Found {len(matched_by_schedule)} schedule(s) with matched transactions")

    # 4. Determine forecast file path and load it
    if not forecast_file:
        forecast_file = os.getenv("BEANSCHEDULE_FORECAST_FILE", "Forecast.bean")

    forecast_path = Path(forecast_file)

    if not forecast_path.exists():
        click.echo(f"Error: Forecast file not found: {forecast_path}", err=True)
        sys.exit(1)

    click.echo(f"\nForecast file: {forecast_path}")

    # Load forecast file entries with auto_accounts plugin to avoid validation errors
    # We only add the plugin when loading the file explicitly here, not when it's
    # included in main.bean, so this doesn't affect normal ledger loading
    forecast_content = forecast_path.read_text()

    # Prepend auto_accounts plugin directive
    forecast_with_plugin = 'plugin "beancount.plugins.auto_accounts"\n\n' + forecast_content

    # Load from string instead of file to use our modified content
    forecast_entries, errors, options_map = loader.load_string(forecast_with_plugin)

    # Update metadata to reflect actual source file (load_string sets filename to "<string>")
    # This is needed for our filename filtering logic later
    forecast_filename_str = str(forecast_path)
    updated_entries = []
    for entry in forecast_entries:
        if isinstance(entry, data.Transaction):
            # Update the meta dict to have the correct filename
            updated_entry = entry._replace(meta={**entry.meta, "filename": forecast_filename_str})
            updated_entries.append(updated_entry)
        else:
            updated_entries.append(entry)
    forecast_entries = updated_entries

    # Check for any remaining errors (should be none with auto_accounts)
    if errors:
        click.echo(f"Warning: {len(errors)} error(s) loading forecast file", err=True)
        for error in errors[:5]:
            click.echo(f"  {error}", err=True)

    # Build forecasts dictionary from Forecast.bean file ONLY
    # Filter to only transactions that originated from the forecast file itself
    # (not forecast-generated transactions created by the forecast plugin)
    forecasts = {}  # schedule-id -> forecast transaction

    # Resolve to absolute path for comparison
    forecast_filename_abs = str(forecast_path.resolve())

    for entry in forecast_entries:
        if isinstance(entry, data.Transaction) and entry.flag == "#" and "schedule-id" in entry.meta:
            # Only include if this transaction came from the forecast file itself
            # Compare absolute paths to handle relative vs absolute path differences
            entry_filename = entry.meta.get("filename", "")
            entry_filename_abs = str(Path(entry_filename).resolve()) if entry_filename else ""

            if entry_filename_abs == forecast_filename_abs:
                schedule_id = entry.meta["schedule-id"]
                # Take the first occurrence (don't overwrite with later ones)
                if schedule_id not in forecasts:
                    forecasts[schedule_id] = entry

    # 5. Filter forecast entries to only those from the forecast file itself
    # (exclude forecast-generated transactions created by the forecast plugin)
    original_forecast_entries = []
    for entry in forecast_entries:
        if isinstance(entry, data.Transaction) and entry.flag == "#" and "schedule-id" in entry.meta:
            entry_filename = entry.meta.get("filename", "")
            entry_filename_abs = str(Path(entry_filename).resolve()) if entry_filename else ""
            if entry_filename_abs == forecast_filename_abs:
                original_forecast_entries.append(entry)

    # Load forecast schedules from the original forecast definitions only
    forecast_schedule_file = load_forecast_schedules(original_forecast_entries)
    if not forecast_schedule_file:
        click.echo("Error: No forecast schedules found in forecast file", err=True)
        sys.exit(1)

    schedule_by_id = {s.id: s for s in forecast_schedule_file.schedules}

    # 6. For each matched schedule, calculate next occurrence
    schedules_to_advance = {}

    for schedule_id, matched_txns in matched_by_schedule.items():
        # Get the forecast transaction for this schedule
        if schedule_id not in forecasts:
            click.echo(f"Warning: Matched transactions for '{schedule_id}' but no forecast found", err=True)
            continue

        # Get the schedule definition
        if schedule_id not in schedule_by_id:
            click.echo(f"Warning: No schedule definition found for '{schedule_id}'", err=True)
            continue

        forecast_txn = forecasts[schedule_id]
        schedule = schedule_by_id[schedule_id]

        # Find most recent matched transaction
        latest_match = max(matched_txns, key=lambda t: t.date)

        # Only advance if the latest match is close to the current forecast date
        # This makes the command idempotent - if the forecast is already ahead of all matches,
        # we don't keep advancing it every time the command runs
        date_window = schedule.match.date_window_days or 3
        days_diff = (forecast_txn.date - latest_match.date).days

        # If the forecast is already more than 2*date_window ahead of the latest match,
        # it's already been advanced - don't advance it again
        if days_diff > 2 * date_window:
            continue

        # Calculate next occurrence after the forecast's current date
        # (since a match means this forecast occurrence is "done")
        # Use the later of: forecast date or matched date
        reference_date = max(forecast_txn.date, latest_match.date)

        from .forecast_advancement import calculate_next_occurrence

        next_date = calculate_next_occurrence(schedule, reference_date)

        if next_date:
            schedules_to_advance[schedule_id] = {
                'forecast_txn': forecast_txn,
                'matched_date': latest_match.date,
                'forecast_date': forecast_txn.date,
                'next_date': next_date,
            }
            click.echo(f"  {schedule_id}: {forecast_txn.date} -> {next_date}")
        else:
            click.echo(f"  {schedule_id}: No future occurrences (schedule may have ended)")

    if not schedules_to_advance:
        click.echo("\nNo forecasts to advance")
        return

    # 7. Update matched forecast transactions
    updated_entries = []
    updated_count = 0

    for entry in forecast_entries:
        # Only process forecast transactions (# flag)
        # Skip Open directives and other entries created by auto_accounts plugin
        if isinstance(entry, data.Transaction) and entry.flag == "#":
            schedule_id = entry.meta.get("schedule-id")

            if schedule_id in schedules_to_advance:
                # Advance this forecast
                info = schedules_to_advance[schedule_id]
                next_date = info['next_date']

                updated_txn = advance_forecast_transaction(entry, next_date)
                updated_entries.append(updated_txn)
                updated_count += 1
            else:
                # Keep unchanged forecast transaction
                updated_entries.append(entry)
        # Ignore all other entries (Open directives, etc.)

    # 8. Write back to file (unless dry-run)
    if dry_run:
        click.echo(f"\nDry-run mode: would update {updated_count} forecast(s)")
    else:
        # Write updated entries (only forecast transactions)
        with open(forecast_path, "w") as f:
            printer.print_entries(updated_entries, file=f)

        click.echo(f"\n✓ Updated {updated_count} forecast(s) in {forecast_path}")


if __name__ == "__main__":
    main()
