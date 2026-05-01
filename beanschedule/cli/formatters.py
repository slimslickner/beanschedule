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
    """
    # Calculate column widths
    id_width = max(len(s.id) for s in schedules)
    id_width = max(id_width, len("ID"))

    payee_width = max(len(s.transaction.payee or "") for s in schedules)
    payee_width = max(payee_width, len("Payee"))
    payee_width = min(payee_width, 30)  # Cap at 30

    # Print header
    click.echo(
        f"{'ID':<{id_width}}  {'Status':<8}  {'RRULE':<30}  {'Payee':<{payee_width}}"
    )
    click.echo("-" * (id_width + 8 + 30 + payee_width + 6))

    # Print schedules
    for s in schedules:
        status = "enabled " if s.enabled else "disabled"
        rrule = s.recurrence.rrule[:30]
        payee = (s.transaction.payee or "")[:payee_width]

        click.echo(
            f"{s.id:<{id_width}}  {status:<8}  {rrule:<30}  {payee:<{payee_width}}"
        )

    click.echo(f"\nTotal: {len(schedules)} schedules")


def print_schedule_csv(schedules: list) -> None:
    """
    Print schedules as comma-separated values (CSV) to stdout.

    Outputs schedule details in CSV format suitable for import into spreadsheet
    applications. Columns include: ID, Enabled status, Frequency, Payee pattern,
    Account, and Expected amount.
    """
    writer = csv.writer(sys.stdout)
    writer.writerow(["ID", "Enabled", "RRULE", "Payee", "Account", "Amount"])

    for s in schedules:
        writer.writerow(
            [
                s.id,
                "true" if s.enabled else "false",
                s.recurrence.rrule,
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
    header = f"{'#':>4} {'Date':>12} {'Payment':>12} {'Principal':>12} {'Interest':>12} {'Balance':>14}"
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


def print_match_table(schedules: list) -> None:
    """Print schedules as a table focused on match criteria (ID, account, amount).

    Displays the schedule ID, the account used for matching, and the expected
    amount (exact ± tolerance, range, or "(any)").
    """
    id_width = max(max(len(s.id) for s in schedules), len("ID"))
    account_width = max(max(len(s.match.account) for s in schedules), len("Account"))

    click.echo(f"{'ID':<{id_width}}  {'Account':<{account_width}}  Amount")
    click.echo("-" * (id_width + account_width + 2 + 2 + 10))

    for s in schedules:
        m = s.match
        if m.amount is not None:
            if m.amount_tolerance is not None:
                amount_str = f"{m.amount} ± {m.amount_tolerance}"
            else:
                amount_str = str(m.amount)
        elif m.amount_min is not None and m.amount_max is not None:
            amount_str = f"{m.amount_min} to {m.amount_max}"
        else:
            amount_str = "(any)"

        click.echo(
            f"{s.id:<{id_width}}  {s.match.account:<{account_width}}  {amount_str}"
        )

    click.echo(f"\nTotal: {len(schedules)} schedules")


def print_postings_table(schedule) -> None:
    """Print a schedule's transaction postings as a table.

    Each posting is one row. Metadata keys are pivoted to columns, with all
    unique keys collected across all postings.
    """
    postings = schedule.transaction.postings
    if not postings:
        click.echo("No postings defined for this schedule.")
        return

    # Collect all metadata keys across all postings (preserving insertion order)
    meta_keys: list[str] = []
    for p in postings:
        for k in p.metadata:
            if k not in meta_keys:
                meta_keys.append(k)

    # Calculate column widths
    account_width = max(max(len(p.account) for p in postings), len("Account"))
    amount_width = max(
        max(
            len(str(p.amount)) if p.amount is not None else len("(auto)")
            for p in postings
        ),
        len("Amount"),
    )
    currency_width = max(
        max(len(p.currency or "") for p in postings),
        len("Currency"),
    )
    role_width = max(
        max(len(p.role or "") for p in postings),
        len("Role"),
    )
    meta_widths = {
        k: max(
            max(len(str(p.metadata.get(k, ""))) for p in postings),
            len(k),
        )
        for k in meta_keys
    }

    # Build header
    header_parts = [
        f"{'Account':<{account_width}}",
        f"{'Amount':<{amount_width}}",
        f"{'Currency':<{currency_width}}",
        f"{'Role':<{role_width}}",
    ]
    for k in meta_keys:
        header_parts.append(f"{k:<{meta_widths[k]}}")
    header = "  ".join(header_parts)
    click.echo(header)
    click.echo("-" * len(header))

    # Print rows
    for p in postings:
        amount_str = str(p.amount) if p.amount is not None else "(auto)"
        row_parts = [
            f"{p.account:<{account_width}}",
            f"{amount_str:<{amount_width}}",
            f"{(p.currency or ''):<{currency_width}}",
            f"{(p.role or ''):<{role_width}}",
        ]
        for k in meta_keys:
            val = str(p.metadata.get(k, ""))
            row_parts.append(f"{val:<{meta_widths[k]}}")
        click.echo("  ".join(row_parts))

    click.echo(f"\nTotal: {len(postings)} postings")


def print_detection_json(candidates: list) -> None:
    """Print detected patterns as JSON."""
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
