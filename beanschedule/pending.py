"""Pending transaction support.

Allows users to stage transactions that haven't yet posted (e.g., online orders,
pending charges) and have them automatically match and enrich imported transactions
when they arrive via the beangulp hook.

A pending transaction:
- Is defined in pending.beancount with #pending tag
- Contains pre-defined splits with detailed posting narration
- Matches on account + amount + date (within 4-day window)
- Is automatically removed after matching (one-time use)

Example pending transaction::

    2026-02-20 ! "Amazon" "Wireless headphones ordered"
      #pending
      Assets:Checking  -89.99 USD
      Expenses:Electronics:Audio  85.00 USD
        narration: "Bose QuietComfort 45"
      Expenses:Shopping:Shipping  4.99 USD
"""

import logging
import os
from datetime import date as date_type
from decimal import Decimal
from pathlib import Path
from typing import Any

from beancount import loader as bc_loader
from beancount.core import amount as bc_amount
from beancount.core import data
from beancount.parser import printer as bc_printer
from pydantic import BaseModel, ConfigDict, Field

from .schema import Posting as PostingTemplate

logger = logging.getLogger(__name__)

# Pending match window (days)
DEFAULT_PENDING_WINDOW_DAYS = 4

# Beancount internal metadata keys to skip when extracting user metadata
_BEANCOUNT_INTERNAL_META: frozenset[str] = frozenset({"filename", "lineno"})


class PendingTransaction(BaseModel):
    """A one-time transaction pending posting and awaiting import match."""

    date: date_type = Field(..., description="Date transaction was created")
    account: str = Field(..., description="Main account to match (first posting)")
    amount: Decimal = Field(..., description="Amount to match (exact)")
    payee: str = Field(..., description="Payee name")
    narration: str = Field(..., description="Transaction narration")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional transaction metadata"
    )
    postings: list[PostingTemplate] = Field(
        ..., description="Pre-defined posting splits"
    )

    model_config = ConfigDict(frozen=False)


def find_pending_file() -> Path | None:
    """
    Find pending transaction file.

    Search priority:
    1. BEANSCHEDULE_PENDING environment variable
    2. pending.beancount in current directory
    3. pending.beancount in parent directory

    Returns:
        Path to pending file or None if not found
    """
    # Check environment variable
    if env_path := os.getenv("BEANSCHEDULE_PENDING"):
        path = Path(env_path)
        if path.exists():
            logger.debug("Found pending file via environment variable: %s", path)
            return path

    # Check current directory
    current = Path("pending.beancount")
    if current.exists():
        logger.debug("Found pending file in current directory: %s", current)
        return current

    # Check parent directory
    parent = Path("../pending.beancount")
    if parent.exists():
        logger.debug("Found pending file in parent directory: %s", parent)
        return parent

    logger.debug("No pending file found")
    return None


def is_pending_marker(entry: data.Transaction) -> bool:
    """
    Check if transaction is a pending marker.

    A transaction is a pending marker if it has:
    - #pending tag

    Args:
        entry: Transaction to check

    Returns:
        True if this is a pending marker
    """
    # Check tags (Beancount stores tags without the # symbol)
    return bool(entry.tags and "pending" in entry.tags)


def load_pending_transactions(file_path: Path) -> list[PendingTransaction]:
    """
    Load pending transactions from beancount file.

    Parses the beancount file and extracts all transactions marked as pending
    (#pending tag).

    Automatically injects the auto_accounts plugin at runtime (without modifying the file)
    to create account open directives for any accounts used in pending transactions.

    Args:
        file_path: Path to pending.beancount file

    Returns:
        List of PendingTransaction objects
    """
    logger.info("Loading pending transactions from %s", file_path)

    try:
        # Read file content
        content = file_path.read_text()

        # Check for ;; comments and warn about using narration metadata instead
        if ";;" in content:
            logger.warning(
                "Pending file contains ;; comments. "
                "Consider using posting-level 'narration:' metadata instead for better integration. "
                'Example: Assets:Checking  -50.00 USD\n  narration: "Your description here"'
            )

        # Prepend auto_accounts plugin directive (in-memory only, doesn't modify file)
        plugin_directive = 'plugin "beancount.plugins.auto_accounts"\n\n'
        modified_content = plugin_directive + content

        # Load from modified string (file remains unchanged on disk)
        entries, errors, options = bc_loader.load_string(modified_content)
        logger.debug("Applied auto_accounts plugin via inline directive injection")

    except Exception as e:
        logger.error("Failed to load pending file %s: %s", file_path, e)
        return []

    # Log any parse warnings
    for error in errors:
        logger.warning("Pending file parse warning: %s", error)

    pending_txns = []

    for entry in entries:
        if not isinstance(entry, data.Transaction):
            continue

        # Check if this is a pending transaction
        if not is_pending_marker(entry):
            continue

        # Extract postings
        if not entry.postings:
            logger.warning("Pending transaction has no postings: %s", entry.date)
            continue

        account = entry.postings[0].account
        first_units = entry.postings[0].units
        if not first_units or first_units.number is None:
            logger.warning("Pending transaction has no amount: %s", entry.date)
            continue

        amount_value = first_units.number

        # Extract transaction-level metadata (skip beancount internals)
        txn_metadata = {
            k: v for k, v in entry.meta.items() if k not in _BEANCOUNT_INTERNAL_META
        }

        # Convert beancount postings to Posting schema
        postings = []
        for p in entry.postings:
            posting_meta: dict[str, Any] = {}
            if p.meta:
                posting_meta = {
                    k: v for k, v in p.meta.items() if k not in _BEANCOUNT_INTERNAL_META
                }

            posting_amount = p.units.number if p.units else None

            postings.append(
                PostingTemplate(
                    account=p.account,
                    amount=posting_amount,
                    metadata=posting_meta,
                )
            )

        # Create PendingTransaction
        try:
            pending = PendingTransaction(
                date=entry.date,
                account=account,
                amount=amount_value,
                payee=entry.payee or "",
                narration=entry.narration or "",
                metadata=txn_metadata,
                postings=postings,
            )
            pending_txns.append(pending)
            logger.debug("Loaded pending transaction: %s - %s", entry.date, entry.payee)
        except Exception as e:
            logger.error(
                "Failed to create PendingTransaction for %s: %s", entry.date, e
            )
            continue

    logger.info("Loaded %d pending transaction(s)", len(pending_txns))
    return pending_txns


def match_pending_transaction(
    txn: data.Transaction,
    pending_transactions: list[PendingTransaction],
    window_days: int = DEFAULT_PENDING_WINDOW_DAYS,
) -> PendingTransaction | None:
    """
    Match imported transaction against pending transactions.

    Match criteria (ALL must match):
    1. Account - exact match of first posting account
    2. Amount - exact match of first posting amount
    3. Date - imported date within window_days of pending date

    Args:
        txn: Imported transaction from beangulp
        pending_transactions: List of pending transactions
        window_days: Match window in days (default 4)

    Returns:
        Matching PendingTransaction or None
    """
    if not txn.postings or not txn.postings[0].units:
        return None

    main_account = txn.postings[0].account
    txn_amount = txn.postings[0].units.number

    for pending in pending_transactions:
        # Check account (exact)
        if pending.account != main_account:
            continue

        # Check amount (exact)
        if pending.amount != txn_amount:
            continue

        # Check date window
        days_diff = abs((txn.date - pending.date).days)
        if days_diff > window_days:
            continue

        # Match found
        logger.info(
            "Matched pending transaction (pending: %s, imported: %s, diff: %d days)",
            pending.date,
            txn.date,
            days_diff,
        )
        return pending

    return None


def enrich_from_pending(
    txn: data.Transaction,
    pending: PendingTransaction,
) -> data.Transaction:
    """
    Enrich transaction with pending template.

    Applies pre-defined postings and metadata from pending transaction to
    imported transaction. Overrides payee/narration if specified in pending.

    Args:
        txn: Imported transaction
        pending: Matched pending transaction

    Returns:
        Enriched transaction
    """
    # Add pending metadata: start with existing, then apply pending metadata
    new_meta = txn.meta.copy()
    new_meta.update(pending.metadata)
    new_meta["pending_matched_date"] = pending.date.isoformat()

    # Use pending payee/narration
    payee = pending.payee or txn.payee
    narration = pending.narration or txn.narration

    # Apply pending postings (replace imported postings)
    first_units = txn.postings[0].units if txn.postings else None
    currency = first_units.currency if first_units else "USD"

    new_postings = []
    for p in pending.postings:
        units = None
        if p.amount is not None:
            units = bc_amount.Amount(p.amount, currency)

        posting = data.Posting(
            account=p.account,
            units=units,
            cost=None,
            price=None,
            flag=None,
            meta=dict(p.metadata) if p.metadata else None,
        )
        new_postings.append(posting)

    logger.debug(
        "Enriched transaction with pending template (%d postings)", len(new_postings)
    )

    return txn._replace(
        meta=new_meta,
        payee=payee,
        narration=narration,
        postings=new_postings,
    )


def remove_pending_transactions(
    file_path: Path, matched_pending: list["PendingTransaction"]
) -> None:
    """
    Remove matched pending transactions from file.

    Reads the beancount file, filters out transactions that match the provided
    pending transactions (by date, payee, amount), and writes back to the file.

    Args:
        file_path: Path to pending.beancount
        matched_pending: List of matched PendingTransaction objects to remove
    """
    logger.info(
        "Removing %d matched pending transaction(s) from %s",
        len(matched_pending),
        file_path,
    )

    try:
        entries, _errors, _options = bc_loader.load_file(str(file_path))
    except Exception as e:
        logger.error("Failed to load pending file for removal %s: %s", file_path, e)
        return

    # Create a set of (date, payee, amount) tuples from pending transactions
    remove_set = {(p.date, p.payee, p.amount) for p in matched_pending}

    # Filter out matched transactions
    kept_entries = []
    removed_count = 0

    for entry in entries:
        if isinstance(entry, data.Transaction):
            entry_key = (
                entry.date,
                entry.payee,
                entry.postings[0].units.number
                if entry.postings and entry.postings[0].units
                else None,
            )
            if entry_key in remove_set:
                removed_count += 1
                logger.debug(
                    "Removing pending transaction: %s - %s", entry.date, entry.payee
                )
                continue

        kept_entries.append(entry)

    # Write back to file
    try:
        with open(file_path, "w") as f:
            for entry in kept_entries:
                bc_printer.print_entry(entry, file=f)
        logger.info(
            "Removed %d matched pending transaction(s) from %s",
            removed_count,
            file_path,
        )
    except Exception as e:
        logger.error("Failed to write pending file after removal %s: %s", file_path, e)
