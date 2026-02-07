"""Output formatting functions for CLI commands."""

import csv
import json
import sys

import click


def print_schedule_table(schedules: list) -> None:
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


def print_schedule_csv(schedules: list) -> None:
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


def print_amortization_table(dated_splits):
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


def print_amortization_csv(dated_splits):
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
            ],
        )


def print_amortization_json(dated_splits, summary_info):
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
            },
        )

    output = {
        "summary": summary_info,
        "payments": payments,
    }

    click.echo(json.dumps(output, indent=2))


def print_detection_table(candidates: list) -> None:
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


def print_detection_json(candidates: list) -> None:
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
            },
        )

    click.echo(json.dumps(output, indent=2))
