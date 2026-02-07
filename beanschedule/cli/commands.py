"""Click CLI commands for beanschedule."""

import json
import logging
import sys
import traceback
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import click
import yaml
from beancount import loader as beancount_loader
from beancount.core import data
from dateutil.relativedelta import relativedelta

from beanschedule import __version__
from beanschedule.loader import load_schedules_from_path
from beanschedule.recurrence import RecurrenceEngine
from beanschedule.utils import slugify

from .builders import (
    build_schedule_dict,
    complete_schedule_id,
    day_of_week_from_date,
    extract_transaction_details,
    save_detected_schedules,
)
from .formatters import (
    print_amortization_csv,
    print_amortization_json,
    print_amortization_table,
    print_detection_json,
    print_detection_table,
    print_schedule_csv,
    print_schedule_table,
)

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
        schedule_file = load_schedules_from_path(path_obj)
        if schedule_file is None:
            click.echo(f"Error: Path is neither a file nor a directory: {path_obj}", err=True)
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
        schedule_file = load_schedules_from_path(path_obj)
        if schedule_file is None:
            click.echo(f"Error: Path is neither a file nor a directory: {path_obj}", err=True)
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
            print_schedule_table(schedules)
        elif output_format == "json":
            schedules_data = [s.model_dump(mode="python") for s in schedules]
            click.echo(json.dumps(schedules_data, indent=2, default=str))
        elif output_format == "csv":
            print_schedule_csv(schedules)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        sys.exit(1)


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
        schedule_file = load_schedules_from_path(path_obj)
        if schedule_file is None:
            click.echo(f"Error: Path not found: {path_obj}", err=True)
            sys.exit(1)

        # Find schedule by ID
        schedule = next((s for s in schedule_file.schedules if s.id == schedule_id), None)
        if schedule is None:
            click.echo(f"Error: Schedule '{schedule_id}' not found", err=True)
            sys.exit(1)

        # Generate occurrences using shared utility (consistent with hook & plugin)
        from beanschedule.utils import generate_schedule_occurrences

        engine = RecurrenceEngine()
        occurrences = generate_schedule_occurrences(schedule, engine, start, end)

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
def show(  # noqa: PLR0912, PLR0915
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
        schedule_file = load_schedules_from_path(path_obj)
        if schedule_file is None:
            click.echo(f"Error: Path not found: {path_obj}", err=True)
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
        # NOTE: For consistency with the plugin's duplicate prevention, we start from
        # tomorrow if no explicit from_date is provided. This avoids showing forecasts
        # for today, which might already have actual imported transactions.
        today = date.today()  # noqa: DTZ011
        from_date = (
            today + timedelta(days=1) if from_date is None else from_date.date()
        )

        to_date = (
            from_date + timedelta(days=count * 45)
            if to_date is None
            else to_date.date()
        )

        # Generate occurrences using shared utility (consistent with hook & plugin)
        from beanschedule.utils import generate_schedule_occurrences

        engine = RecurrenceEngine()
        occurrences = generate_schedule_occurrences(schedule, engine, from_date, to_date)

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
                f"  Amount range: {schedule.match.amount_min} to {schedule.match.amount_max}",
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
def amortize(  # noqa: PLR0912, PLR0915, PLR0913
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
        schedule_file = load_schedules_from_path(path_obj)
        if schedule_file is None:
            click.echo(f"Error: Path not found: {path_obj}", err=True)
            sys.exit(1)

        # Find schedule by ID
        schedule = next((s for s in schedule_file.schedules if s.id == schedule_id), None)
        if schedule is None:
            click.echo(f"Error: Schedule '{schedule_id}' not found", err=True)
            sys.exit(1)

        # Check if schedule has amortization configured
        if schedule.amortization is None:
            click.echo(
                f"Error: Schedule '{schedule_id}' does not have amortization configured",
                err=True,
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

            from decimal import Decimal  # noqa: PLC0415

            from beanschedule.amortization import (  # noqa: PLC0415
                build_liability_balance_index,
                compute_stateful_splits,
            )
            from beanschedule.plugins.schedules import _get_principal_account  # noqa: PLC0415

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

            today = date.today()  # noqa: DTZ011
            # NOTE: For consistency with the plugin's duplicate prevention, we start from
            # tomorrow if no explicit from_date is provided. This avoids showing forecasts
            # for today, which might already have actual imported transactions.
            forecast_start = today + timedelta(days=1)
            horizon_months = horizon or 12
            forecast_end = today + relativedelta(months=horizon_months)

            # Determine occurrence dates: use payment_day_of_month if set, otherwise transaction
            # recurrence
            from copy import deepcopy  # noqa: PLC0415
            from beanschedule.utils import generate_schedule_occurrences

            engine = RecurrenceEngine()
            if schedule.amortization.payment_day_of_month:
                # Create a temporary schedule with payment_day_of_month as the recurrence day
                # This ensures the recurrence engine generates dates on actual payment dates
                amort_schedule = deepcopy(schedule)
                amort_schedule.recurrence.day_of_month = schedule.amortization.payment_day_of_month
                occurrences = generate_schedule_occurrences(
                    amort_schedule, engine, forecast_start, forecast_end
                )
            else:
                # Use transaction recurrence dates
                occurrences = generate_schedule_occurrences(
                    schedule, engine, forecast_start, forecast_end
                )

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
                    f"({schedule.amortization.compounding.value})",
                )
                click.echo(f"Monthly Payment: ${schedule.amortization.monthly_payment:,.2f}")
                if schedule.amortization.extra_principal:
                    click.echo(
                        f"Extra Principal: ${schedule.amortization.extra_principal:,.2f}/month",
                    )
                click.echo(
                    f"Forecast Horizon: {horizon_months} months ({len(all_dated_splits)} payments)",
                )
                if all_dated_splits and all_dated_splits[-1][1].remaining_balance == Decimal("0"):
                    click.echo("Loan pays off within forecast horizon")

        # ── static mode: derive from original loan terms ─────────────────────
        else:
            from beanschedule.amortization import AmortizationSchedule  # noqa: PLC0415

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
                    f"({schedule.amortization.term_months // 12} years)",
                )
                click.echo(f"Monthly Payment: ${amort.payment:,.2f}")
                if schedule.amortization.extra_principal:
                    click.echo(
                        f"Extra Principal: ${schedule.amortization.extra_principal:,.2f}/month",
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
                    f"Interest/Principal Ratio: {(total_interest / total_principal * 100):.1f}%",
                )
            click.echo()

        if summary_only:
            return

        display_splits = all_dated_splits[:limit] if limit else all_dated_splits

        if output_format == "table":
            print_amortization_table(display_splits)
            if limit and len(all_dated_splits) > limit:
                click.echo(f"\n... {len(all_dated_splits) - limit} more payments")
                click.echo(f"\nFinal payment #{len(all_dated_splits)}:")
                _, final = all_dated_splits[-1]
                click.echo(f"  Payment: ${final.total_payment:,.2f}")
                click.echo(f"  Principal: ${final.principal:,.2f}")
                click.echo(f"  Interest: ${final.interest:,.2f}")
                click.echo(f"  Balance: ${final.remaining_balance:,.2f}")

        elif output_format == "csv":
            print_amortization_csv(display_splits)

        elif output_format == "json":
            print_amortization_json(display_splits, summary_info)

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
def create(  # noqa: PLR0912, PLR0915
    ledger_path: str,
    target_date,
    output_path: str | None,
    schedules_dir: str,
):
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
        from beanschedule.types import FrequencyType  # noqa: PLC0415

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
    "--schedules-path",
    type=click.Path(),
    default="schedules",
    help="Path to existing schedules to skip (default: schedules/)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format (default: table)",
)
def detect(  # noqa: PLR0912, PLR0915, PLR0913
    ledger_path: str,
    confidence: float,
    fuzzy_threshold: float,
    amount_tolerance: float,
    min_occurrences: int,
    output_dir: str | None,
    schedules_path: str,
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
    from beanschedule.detector import RecurrenceDetector  # noqa: PLC0415

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

        if min_occurrences < 2:  # noqa: PLR2004
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
            click.echo("Try adjusting thresholds: lower --confidence or --min-occurrences")
            sys.exit(0)

        # Filter out schedules that already exist
        existing_ids: set[str] = set()
        schedule_file = load_schedules_from_path(Path(schedules_path))
        if schedule_file is not None:
            existing_ids = {s.id for s in schedule_file.schedules}
            skipped_ids = {c.schedule_id for c in candidates} & existing_ids
            if skipped_ids:
                candidates = [c for c in candidates if c.schedule_id not in existing_ids]
                click.echo(
                    f"\nSkipped {len(skipped_ids)} already-existing schedule(s): "
                    + ", ".join(sorted(skipped_ids)),
                )

        if not candidates:
            click.echo("No new recurring patterns detected (all matched existing schedules).")
            sys.exit(0)

        # Display results
        click.echo(f"\nDetected {len(candidates)} recurring patterns:\n")

        if output_format == "table":
            print_detection_table(candidates)
        elif output_format == "json":
            print_detection_json(candidates)

        # Show top candidates with schedule creation guidance
        if output_format == "table":
            click.echo(f"\n{'─' * 120}")
            click.echo(
                "\nTo manually create schedules for detected patterns, use `beanschedule create`:",
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
            saved_count = save_detected_schedules(candidates, output_path)
            click.echo(f"\n✓ Saved {saved_count} schedules to: {output_path}")
            click.echo("\nNext steps:")
            click.echo(f"  1. Review: beanschedule list {output_path}")
            click.echo(f"  2. Validate: beanschedule validate {output_path}")
            click.echo("  3. Customize as needed (payee patterns, amounts, etc.)")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        sys.exit(1)


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


@main.command(name="skip")
@click.argument("schedule_id", required=False)
@click.argument("dates", nargs=-1)
@click.option(
    "--schedules-path",
    "-s",
    type=click.Path(exists=True),
    default=None,
    help="Path to schedules.yaml or schedules/ directory (auto-discovered if not specified)",
)
@click.option(
    "--reason",
    "-r",
    type=str,
    default=None,
    help="Reason for skipping (will be included in transaction narration)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Append to this file instead of printing to stdout",
)
@click.option(
    "--select",
    is_flag=True,
    help="Interactive mode: select from missing scheduled transactions in ledger",
)
@click.option(
    "--ledger",
    "-l",
    type=click.Path(exists=True),
    default=None,
    help="Ledger file to scan for missing transactions (required with --select)",
)
def skip(
    schedule_id: str | None,
    dates: tuple[str],
    schedules_path: str | None,
    reason: str | None,
    output: str | None,
    select: bool,
    ledger: str | None,
):
    """Generate skip marker transactions for scheduled occurrences.

    Marks specific occurrences of a scheduled transaction as intentionally skipped
    without creating a placeholder or warning. The generated transaction includes
    schedule_id metadata so the hook recognizes it as a skip marker.

    Two modes:

    1. DIRECT MODE: Provide SCHEDULE_ID and DATES
       beanschedule skip credit-card-payment 2026-02-15

    2. INTERACTIVE MODE: Use --select to choose from missing transactions
       beanschedule skip --select --ledger ledger.beancount

    Examples:
        # Direct mode: skip specific dates
        beanschedule skip credit-card-payment 2026-02-15
        beanschedule skip gym-membership 2026-02-15 2026-07-15 --reason "Traveling"
        beanschedule skip rent-payment 2026-03-01 --reason "Prepaid" --output ledger.beancount

        # Interactive mode: select from missing transactions
        beanschedule skip --select --ledger ledger.beancount
    """
    try:
        from beanschedule.constants import META_SCHEDULE_ID, META_SCHEDULE_SKIPPED
        from beanschedule.loader import load_schedules_from_path, get_enabled_schedules
        from beanschedule.hook import schedule_hook
        from beancount import loader as beancount_loader
        from pathlib import Path

        # Determine schedules path
        if schedules_path is None:
            schedules_path = "schedules.yaml" if Path("schedules.yaml").exists() else "schedules"

        path_obj = Path(schedules_path)

        # Load schedules
        schedule_file = load_schedules_from_path(path_obj)
        if schedule_file is None:
            click.echo(f"Error: Could not load schedules from {path_obj}", err=True)
            sys.exit(1)

        # Interactive selection mode
        if select:
            if not ledger:
                click.echo("Error: --ledger is required with --select", err=True)
                sys.exit(1)

            ledger_path = Path(ledger)
            entries, load_errors, _options = beancount_loader.load_file(str(ledger_path))
            for err in load_errors:
                logger.warning("Ledger load warning: %s", err)

            # Get today's date for date range calculation
            from datetime import datetime, timedelta
            today = datetime.now().date()
            start_date = today - timedelta(days=90)
            end_date = today + timedelta(days=90)

            # Find missing schedules using hook logic
            enabled_schedules = get_enabled_schedules(schedule_file)
            from beanschedule.utils import generate_all_schedule_occurrences
            from beanschedule.recurrence import RecurrenceEngine

            recurrence_engine = RecurrenceEngine()
            expected_occurrences = generate_all_schedule_occurrences(
                enabled_schedules, recurrence_engine, start_date, end_date
            )

            # Get matched transactions from ledger
            from beanschedule.hook import _match_ledger_transactions_lazy

            matched = _match_ledger_transactions_lazy(entries, expected_occurrences, enabled_schedules)

            # Build list of missing occurrences
            missing = []
            for account, sched_dates in expected_occurrences.items():
                for sched, expected_date in sched_dates:
                    if (sched.id, expected_date) not in matched:
                        missing.append((sched, expected_date))

            if not missing:
                click.echo("No missing scheduled transactions found in date range.")
                sys.exit(0)

            # Sort by date (oldest first, to highlight overdue)
            missing.sort(key=lambda x: x[1])

            # Display options and let user select
            click.echo("\nMissing scheduled transactions (sorted by date, oldest first):\n")
            for i, (sched, exp_date) in enumerate(missing, 1):
                # Mark overdue items with asterisk
                overdue = " *" if exp_date < today else ""
                click.echo(f"{i:2}. {exp_date} - {sched.id:30} ({sched.transaction.payee}){overdue}")

            click.echo("\nEnter dates to skip (comma-separated numbers, or 'all'):")
            selection = click.prompt("Selection")

            if selection.lower() == "all":
                selected = missing
            else:
                try:
                    indices = [int(x.strip()) - 1 for x in selection.split(",")]
                    selected = [missing[i] for i in indices if 0 <= i < len(missing)]
                except (ValueError, IndexError):
                    click.echo("Invalid selection", err=True)
                    sys.exit(1)

            if not selected:
                click.echo("No items selected.")
                sys.exit(0)

            # Generate skip markers for selected items
            skip_markers = []
            for sched, skip_date in selected:
                marker = _generate_skip_marker(sched, skip_date, reason)
                skip_markers.append(marker)

            output_text = "\n".join(skip_markers)

            if output is None:
                click.echo(output_text)
            else:
                output_path = Path(output)
                with open(output_path, "a") as f:
                    f.write("\n" + output_text + "\n")
                click.echo(f"✓ Skip markers appended to {output_path}", err=False)

        else:
            # Direct mode: SCHEDULE_ID and DATES required
            if not schedule_id or not dates:
                click.echo("Error: SCHEDULE_ID and DATES required (or use --select for interactive mode)", err=True)
                sys.exit(1)

            # Find the schedule
            schedule = next((s for s in schedule_file.schedules if s.id == schedule_id), None)
            if schedule is None:
                click.echo(f"Error: Schedule '{schedule_id}' not found", err=True)
                sys.exit(1)

            # Parse dates
            parsed_dates = []
            for date_str in dates:
                try:
                    parsed_dates.append(date.fromisoformat(date_str))
                except ValueError:
                    click.echo(f"Error: Invalid date format '{date_str}'. Use YYYY-MM-DD", err=True)
                    sys.exit(1)

            # Generate skip markers
            skip_markers = []
            for d in parsed_dates:
                marker = _generate_skip_marker(schedule, d, reason)
                skip_markers.append(marker)

            # Output
            output_text = "\n".join(skip_markers)

            if output is None:
                click.echo(output_text)
            else:
                output_path = Path(output)
                with open(output_path, "a") as f:
                    f.write("\n" + output_text + "\n")
                click.echo(f"✓ Skip markers appended to {output_path}", err=False)

    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        sys.exit(1)


def _generate_skip_marker(schedule, skip_date: date, reason: str | None = None) -> str:
    """
    Generate a Beancount skip marker transaction.

    Args:
        schedule: The Schedule object
        skip_date: The date to skip
        reason: Optional reason for skipping

    Returns:
        Formatted Beancount transaction as a string
    """
    from beanschedule.constants import META_SCHEDULE_ID, META_SCHEDULE_SKIPPED

    payee = schedule.transaction.payee
    account = schedule.match.account

    # Format narration
    if reason:
        narration = f"[SKIPPED] {reason}"
    else:
        narration = "[SKIPPED]"

    # Format transaction with standard flag (*) and #skipped tag
    lines = [
        f"{skip_date.isoformat()} * \"{payee}\" \"{narration}\"",
        f"  #skipped",
        f"  {META_SCHEDULE_ID}: \"{schedule.id}\"",
        f"  {META_SCHEDULE_SKIPPED}: \"true\"",
        f"  {account}  0 USD",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    main()
