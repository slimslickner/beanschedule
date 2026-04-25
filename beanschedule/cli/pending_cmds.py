"""CLI commands for managing pending one-time transactions."""

import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import click

from beanschedule.pending import (
    convert_semicolon_comments_to_narration,
    find_pending_file,
    load_pending_transactions,
)

logger = logging.getLogger(__name__)


@click.group()
def pending():
    """Manage pending one-time transactions.

    Stage transactions that will post in the future (e.g., online orders,
    pending charges) and have them automatically enrich when imported.
    """


@pending.command("create")
@click.option(
    "--account",
    "-a",
    required=True,
    help="Main account (e.g., Assets:Checking)",
)
@click.option(
    "--amount",
    "-m",
    required=True,
    type=Decimal,
    help="Total amount (e.g., -89.99)",
)
@click.option(
    "--date",
    "-d",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Expected date (YYYY-MM-DD)",
)
@click.option(
    "--payee",
    "-p",
    required=True,
    help="Payee name",
)
@click.option(
    "--narration",
    "-n",
    default="",
    help="Transaction narration",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="pending.beancount",
    help="Output file (default: pending.beancount)",
)
def create_pending(
    account: str,
    amount: Decimal,
    date: datetime,
    payee: str,
    narration: str,
    output: str,
):
    """Create a new pending transaction with interactive split entry.

    Examples:

        beanschedule pending create \\
          --account Assets:Checking \\
          --amount -89.99 \\
          --date 2026-02-20 \\
          --payee "Amazon" \\
          --narration "Wireless headphones"

        beanschedule pending create \\
          --account Assets:Checking \\
          --amount -127.45 \\
          --date 2026-02-22 \\
          --payee "Whole Foods" \\
          --narration "Groceries"
    """
    # date comes as datetime from click.DateTime; convert to date for formatting
    txn_date = date.date()

    click.echo("\nCreating pending transaction")
    click.echo(f"   Main account: {account} ({amount})")
    click.echo(f"   Payee: {payee}")
    click.echo(f"   Date: {txn_date}")
    click.echo()

    # Interactive split entry
    splits = []
    remaining = abs(amount)
    split_num = 1

    while True:
        click.echo(f"Split {split_num}:")
        split_account = click.prompt("  Account", type=str)

        # Suggest remaining balance
        remaining_str = f"remaining: {remaining:.2f}"
        if remaining > 0:
            default_amount = remaining
            prompt_text = f"  Amount [{remaining_str}]"
        else:
            prompt_text = f"  Amount [{remaining_str}]"
            default_amount = None

        if default_amount is not None:
            split_amount = click.prompt(
                prompt_text, type=Decimal, default=default_amount
            )
        else:
            split_amount = click.prompt(prompt_text, type=Decimal)

        split_narration = click.prompt(
            "  Narration (optional)", default="", show_default=False
        )

        splits.append(
            {
                "account": split_account,
                "amount": split_amount,
                "narration": split_narration,
            }
        )

        remaining -= split_amount

        # Check if balanced
        if abs(remaining) < Decimal("0.01"):
            click.echo("Balanced!")
            break

        # Ask to add more
        if not click.confirm(f"\nAdd another split? (remaining: {remaining:.2f})"):
            if abs(remaining) > Decimal("0.01"):
                click.echo(
                    f"\nWarning: Amount not balanced (remaining: {remaining:.2f})",
                    err=True,
                )
                if not click.confirm("Continue anyway?"):
                    click.echo("Cancelled.")
                    return
            break

        split_num += 1
        click.echo()

    # Generate beancount transaction
    output_path = Path(output)

    lines = []
    lines.append(f'{txn_date.strftime("%Y-%m-%d")} ! "{payee}" "{narration}" #pending')
    lines.append(f"  {account}  {amount} USD")

    for split in splits:
        lines.append(f"  {split['account']}  {split['amount']} USD")
        if split["narration"]:
            lines.append(f'    narration: "{split["narration"]}"')

    lines.append("")  # Blank line

    # Append to file
    with open(output_path, "a") as f:
        f.write("\n".join(lines))

    click.echo("\nPending transaction created!")
    click.echo(f"  File: {output_path}")
    click.echo(f"  Splits: {len(splits)}")


@pending.command("list")
@click.option(
    "--file",
    "-f",
    type=click.Path(exists=True),
    help="Pending transactions file (auto-detected if not specified)",
)
def list_pending(file: str):
    """List all pending transactions.

    Examples:

        beanschedule pending list
        beanschedule pending list --file my-pending.beancount
    """
    # Find pending file if not specified
    if not file:
        pending_file = find_pending_file()
        if not pending_file:
            click.echo("No pending.beancount file found", err=True)
            click.echo("   Create one with: beanschedule pending create", err=True)
            return
        file = str(pending_file)

    pending_path = Path(file)
    pending_txns = load_pending_transactions(pending_path)

    if not pending_txns:
        click.echo("No pending transactions found")
        return

    click.echo(f"\nPending transactions ({len(pending_txns)} total):\n")

    # Sort by date
    for txn in sorted(pending_txns, key=lambda t: t.date):
        click.echo(f"  {txn.date} | {txn.payee:30} | {txn.amount:>10}")
        click.echo(f"    Account: {txn.account}")
        if txn.narration:
            click.echo(f"    Narration: {txn.narration}")
        if len(txn.postings) > 1:
            click.echo(f"    Postings: {len(txn.postings)} splits")
        click.echo()


@pending.command("clean")
@click.option(
    "--file",
    "-f",
    type=click.Path(exists=True),
    help="Pending transactions file (auto-detected if not specified)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be removed without making changes",
)
def clean_pending(file: str, dry_run: bool):
    """Clean up empty pending file.

    Removes the pending file if it contains no pending transactions.

    Examples:

        beanschedule pending clean
        beanschedule pending clean --dry-run
    """
    # Find pending file if not specified
    if not file:
        pending_file = find_pending_file()
        if not pending_file:
            click.echo("No pending.beancount file found")
            return
        file = str(pending_file)

    pending_path = Path(file)
    pending_txns = load_pending_transactions(pending_path)

    if not pending_txns:
        if dry_run:
            click.echo(f"Would remove empty file: {file}")
        else:
            pending_path.unlink(missing_ok=True)
            click.echo(f"Cleaned up empty pending file: {file}")
    else:
        click.echo(
            f"Warning: File contains {len(pending_txns)} pending transaction(s) - not cleaning",
            err=True,
        )


@pending.command("fix")
@click.option(
    "--file",
    "-f",
    type=click.Path(exists=True),
    help="Pending transactions file (auto-detected if not specified)",
)
@click.option(
    "--dry-run",
    "-n",
    is_flag=True,
    help="Show what would be changed without making changes",
)
def fix_pending(file: str, dry_run: bool):
    """Convert ;; posting comments to narration: metadata.

    Transforms ;; comments on posting lines into proper narration metadata.
    Run this before importing to fix deprecated comment syntax.

    Examples:

        beanschedule pending fix
        beanschedule pending fix --dry-run
        beanschedule pending fix --file my-pending.beancount
    """
    # Find pending file if not specified
    if not file:
        pending_file = find_pending_file()
        if not pending_file:
            click.echo("No pending.beancount file found", err=True)
            click.echo("   Create one with: beanschedule pending create", err=True)
            return
        file = str(pending_file)

    pending_path = Path(file)
    original_content = pending_path.read_text()

    # Check if file contains any ;; comments
    if ";;" not in original_content:
        click.echo(f"No ;; comments found in {pending_path}")
        return

    # Convert comments
    fixed_content = convert_semicolon_comments_to_narration(original_content)

    # Count changes
    original_lines = original_content.splitlines()
    fixed_lines = fixed_content.splitlines()
    changes = sum(1 for o, f in zip(original_lines, fixed_lines) if o != f)

    if dry_run:
        click.echo(f"Would fix {changes} line(s) in {pending_path}:")
        click.echo("\n--- Changes preview ---")
        diff_lines = []
        for i, (orig, fixed) in enumerate(zip(original_lines, fixed_lines), 1):
            if orig != fixed:
                diff_lines.append(f"  Line {i}:")
                diff_lines.append(f"    - {orig}")
                diff_lines.append(f"    + {fixed}")
        click.echo("\n".join(diff_lines))
        click.echo("\n--- End preview ---")
    else:
        pending_path.write_text(fixed_content)
        click.echo(f"Fixed {changes} line(s) in {pending_path}")
