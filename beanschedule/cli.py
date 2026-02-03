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
import pydantic
import yaml
from beancount import loader as beancount_loader
from beancount.core import data
from dateutil.relativedelta import relativedelta

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
    except (ValueError, OSError, yaml.YAMLError, pydantic.ValidationError):
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

    if start > end:
        click.echo("Error: Start date must be before or equal to end date", err=True)
        sys.exit(1)

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
                f"  Amount range: {schedule.match.amount_min} to {schedule.match.amount_max}"
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
@click.argument("schedule_id", shell_complete=complete_schedule_id)
@click.option(
    "--schedules-path",
    type=click.Path(exists=True),
    default="schedules",
    help="Path to schedules file or directory (default: schedules)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "csv", "json"], case_sensitive=False),
    default="table",
    help="Output format (default: table)",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Limit number of payments to display (default: all)",
)
@click.option(
    "--summary-only",
    is_flag=True,
    help="Show only summary statistics, not full table",
)
@click.option(
    "--ledger",
    "-l",
    "ledger_path",
    type=click.Path(exists=True),
    default=None,
    help="Path to Beancount ledger file (required for stateful amortization)",
)
@click.option(
    "--horizon",
    type=int,
    default=None,
    help="Forecast horizon in months for stateful mode (default: 12)",
)
def amortize(
    schedule_id: str,
    schedules_path: str,
    output_format: str,
    limit: int | None,
    summary_only: bool,
    ledger_path: str | None,
    horizon: int | None,
):
    """Display amortization schedule for a loan.

    SCHEDULE_ID: The ID of the schedule with amortization configuration

    Supports both static mode (original loan terms) and stateful mode
    (balance read from ledger via --ledger). Stateful schedules require --ledger.

    Shows a detailed amortization table with date, payment amount,
    principal, interest, and remaining balance for each payment.

    Examples:
        beanschedule amortize mortgage-payment
        beanschedule amortize auto-loan --limit 12
        beanschedule amortize student-loan --format csv > schedule.csv
        beanschedule amortize mortgage-payment --summary-only
        beanschedule amortize mortgage-payment -l ledger.beancount
        beanschedule amortize mortgage-payment -l ledger.beancount --horizon 24
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
        schedule = next((s for s in schedule_file.schedules if s.id == schedule_id), None)
        if schedule is None:
            click.echo(f"Error: Schedule '{schedule_id}' not found", err=True)
            sys.exit(1)

        # Check if schedule has amortization configured
        if schedule.amortization is None:
            click.echo(
                f"Error: Schedule '{schedule_id}' does not have amortization configured", err=True
            )
            click.echo("\nAdd an 'amortization' section to your schedule YAML:", err=True)
            click.echo("  amortization:", err=True)
            click.echo("    principal: 300000.00", err=True)
            click.echo("    annual_rate: 0.0675", err=True)
            click.echo("    term_months: 360", err=True)
            click.echo("    start_date: 2024-01-01", err=True)
            sys.exit(1)

        # ── stateful mode: read balance from ledger ──────────────────────────
        if schedule.amortization.balance_from_ledger:
            if not ledger_path:
                click.echo(
                    "Error: --ledger is required for stateful amortization schedules",
                    err=True,
                )
                sys.exit(1)

            from .amortization import build_liability_balance_index, compute_stateful_splits
            from .plugins.schedules import _get_principal_account

            entries, load_errors, _options = beancount_loader.load_file(ledger_path)
            for err in load_errors:
                logger.warning("Ledger load warning: %s", err)

            principal_account = _get_principal_account(schedule)
            if not principal_account:
                click.echo(
                    f"Error: No posting with role='principal' in schedule '{schedule_id}'",
                    err=True,
                )
                sys.exit(1)

            balances = build_liability_balance_index(entries, {principal_account})
            if principal_account not in balances:
                click.echo(
                    f"Error: No cleared transactions found for {principal_account}",
                    err=True,
                )
                sys.exit(1)

            balance, balance_date = balances[principal_account]
            if balance <= Decimal("0"):
                click.echo(
                    f"Error: Balance for {principal_account} is zero or negative ({balance})",
                    err=True,
                )
                sys.exit(1)

            today = date.today()
            horizon_months = horizon or 12
            forecast_end = today + relativedelta(months=horizon_months)
            engine = RecurrenceEngine()
            occurrences = engine.generate(schedule, today, forecast_end)

            splits_dict = compute_stateful_splits(
                monthly_payment=schedule.amortization.monthly_payment,
                annual_rate=schedule.amortization.annual_rate,
                compounding=schedule.amortization.compounding.value,
                starting_balance=balance,
                starting_date=balance_date,
                occurrence_dates=occurrences,
                extra_principal=schedule.amortization.extra_principal or Decimal("0"),
            )

            all_dated_splits = sorted(splits_dict.items())

            summary_info = {
                "schedule_id": schedule.id,
                "mode": "stateful",
                "liability_account": principal_account,
                "balance_date": str(balance_date),
                "starting_balance": float(balance),
                "annual_rate": float(schedule.amortization.annual_rate),
                "monthly_payment": float(schedule.amortization.monthly_payment),
                "compounding": schedule.amortization.compounding.value,
            }

            if output_format == "table" or summary_only:
                click.echo(f"Schedule: {schedule.id}")
                click.echo("Mode: Stateful (balance from ledger)")
                click.echo(f"Liability Account: {principal_account}")
                click.echo(f"Balance as of {balance_date}: ${balance:,.2f}")
                click.echo(
                    f"Interest Rate: {schedule.amortization.annual_rate * 100:.3f}% "
                    f"({schedule.amortization.compounding.value})"
                )
                click.echo(f"Monthly Payment: ${schedule.amortization.monthly_payment:,.2f}")
                if schedule.amortization.extra_principal:
                    click.echo(
                        f"Extra Principal: ${schedule.amortization.extra_principal:,.2f}/month"
                    )
                click.echo(
                    f"Forecast Horizon: {horizon_months} months ({len(all_dated_splits)} payments)"
                )
                if all_dated_splits and all_dated_splits[-1][1].remaining_balance == Decimal("0"):
                    click.echo("Loan pays off within forecast horizon")

        # ── static mode: derive from original loan terms ─────────────────────
        else:
            from .amortization import AmortizationSchedule

            amort = AmortizationSchedule(
                principal=schedule.amortization.principal,
                annual_rate=schedule.amortization.annual_rate,
                term_months=schedule.amortization.term_months,
                start_date=schedule.amortization.start_date,
                extra_principal=schedule.amortization.extra_principal,
            )

            full_schedule = amort.generate_full_schedule()
            start_date = schedule.amortization.start_date

            all_dated_splits = [
                (start_date + relativedelta(months=split.payment_number - 1), split)
                for split in full_schedule
            ]

            summary_info = {
                "schedule_id": schedule.id,
                "mode": "static",
                "principal": float(schedule.amortization.principal),
                "annual_rate": float(schedule.amortization.annual_rate),
                "term_months": schedule.amortization.term_months,
                "monthly_payment": float(amort.payment),
            }

            if output_format == "table" or summary_only:
                click.echo(f"Schedule: {schedule.id}")
                click.echo(f"Loan Amount: ${schedule.amortization.principal:,.2f}")
                click.echo(f"Interest Rate: {schedule.amortization.annual_rate * 100:.3f}%")
                click.echo(
                    f"Term: {schedule.amortization.term_months} months "
                    f"({schedule.amortization.term_months // 12} years)"
                )
                click.echo(f"Monthly Payment: ${amort.payment:,.2f}")
                if schedule.amortization.extra_principal:
                    click.echo(
                        f"Extra Principal: ${schedule.amortization.extra_principal:,.2f}/month"
                    )

        # ── shared: totals, limit, output ─────────────────────────────────────
        total_interest = sum(s.interest for _, s in all_dated_splits)
        total_principal = sum(s.principal for _, s in all_dated_splits)
        total_paid = sum(s.total_payment for _, s in all_dated_splits)

        summary_info["total_interest"] = float(total_interest)
        summary_info["total_principal"] = float(total_principal)
        summary_info["total_paid"] = float(total_paid)

        if output_format == "table" or summary_only:
            click.echo(f"\nTotal Interest: ${total_interest:,.2f}")
            click.echo(f"Total Principal: ${total_principal:,.2f}")
            click.echo(f"Total Paid: ${total_paid:,.2f}")
            if total_principal > 0:
                click.echo(
                    f"Interest/Principal Ratio: {(total_interest / total_principal * 100):.1f}%"
                )
            click.echo()

        if summary_only:
            return

        display_splits = all_dated_splits[:limit] if limit else all_dated_splits

        if output_format == "table":
            _print_amortization_table(display_splits)
            if limit and len(all_dated_splits) > limit:
                click.echo(f"\n... {len(all_dated_splits) - limit} more payments")
                click.echo(f"\nFinal payment #{len(all_dated_splits)}:")
                _, final = all_dated_splits[-1]
                click.echo(f"  Payment: ${final.total_payment:,.2f}")
                click.echo(f"  Principal: ${final.principal:,.2f}")
                click.echo(f"  Interest: ${final.interest:,.2f}")
                click.echo(f"  Balance: ${final.remaining_balance:,.2f}")

        elif output_format == "csv":
            _print_amortization_csv(display_splits)

        elif output_format == "json":
            _print_amortization_json(display_splits, summary_info)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        sys.exit(1)


def _print_amortization_table(dated_splits):
    """Print amortization schedule as formatted table.

    Args:
        dated_splits: List of (date, PaymentSplit) tuples, sorted by date.
    """
    header = (
        f"{'#':>4} {'Date':>12} {'Payment':>12} {'Principal':>12} {'Interest':>12} {'Balance':>14}"
    )
    click.echo(header)
    click.echo("-" * len(header))

    for idx, (payment_date, split) in enumerate(dated_splits, 1):
        row = (
            f"{idx:>4} "
            f"{payment_date.strftime('%Y-%m-%d'):>12} "
            f"${split.total_payment:>11,.2f} "
            f"${split.principal:>11,.2f} "
            f"${split.interest:>11,.2f} "
            f"${split.remaining_balance:>13,.2f}"
        )
        click.echo(row)


def _print_amortization_csv(dated_splits):
    """Print amortization schedule as CSV.

    Args:
        dated_splits: List of (date, PaymentSplit) tuples, sorted by date.
    """
    writer = csv.writer(sys.stdout)
    writer.writerow(["#", "Date", "Payment", "Principal", "Interest", "Balance"])

    for idx, (payment_date, split) in enumerate(dated_splits, 1):
        writer.writerow(
            [
                idx,
                payment_date.strftime("%Y-%m-%d"),
                f"{split.total_payment:.2f}",
                f"{split.principal:.2f}",
                f"{split.interest:.2f}",
                f"{split.remaining_balance:.2f}",
            ]
        )


def _print_amortization_json(dated_splits, summary_info):
    """Print amortization schedule as JSON.

    Args:
        dated_splits: List of (date, PaymentSplit) tuples, sorted by date.
        summary_info: Dict of summary metadata to include at top of JSON output.
    """
    payments = []
    for idx, (payment_date, split) in enumerate(dated_splits, 1):
        payments.append(
            {
                "number": idx,
                "date": payment_date.strftime("%Y-%m-%d"),
                "payment": float(split.total_payment),
                "principal": float(split.principal),
                "interest": float(split.interest),
                "balance": float(split.remaining_balance),
            }
        )

    output = {
        "summary": summary_info,
        "payments": payments,
    }

    click.echo(json.dumps(output, indent=2))


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
        transactions = [e for e in entries if isinstance(e, data.Transaction) and e.date == target]

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
                    f"{first_posting.units}" if first_posting and first_posting.units else "?"
                )
                account_str = first_posting.account if first_posting else "?"
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
        try:
            amount_tolerance = Decimal(tolerance_str)
            if amount_tolerance < 0:
                raise ValueError("Tolerance cannot be negative")
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)
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
            f"  2. Review: beanschedule show {schedule_id} --schedules-path {schedules_dir}/",
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
            click.echo(f"Try adjusting thresholds: lower --confidence or --min-occurrences")
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
            click.echo(
                "\nTo manually create schedules for detected patterns, use `beanschedule create`:"
            )
            click.echo("Examples for top patterns:\n")
            for candidate in candidates[:3]:
                cmd = f"  beanschedule create --ledger {ledger_path} --date {candidate.first_date}"
                click.echo(f"  {candidate.confidence * 100:.0f}% confidence - {candidate.payee}")
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


if __name__ == "__main__":
    main()
