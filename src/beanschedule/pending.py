"""Pending transaction support.

Allows users to stage transactions that have not posted yet (an online order, a
pending charge) and have them automatically matched and enriched when they
arrive. Pending transactions live in ``pending.bean``; the main ledger includes
it, and the plugin tags and flags each one so it is obvious.

A pending transaction:

* is any transaction in ``pending.bean`` (the whole file is pending);
* carries pre-defined splits with detailed posting narration;
* matches on account + amount + date (within a four-day window); and
* is removed once matched, so it is one-time use.

Example pending transaction::

    2026-02-20 * "Amazon" "Wireless headphones ordered"
      Assets:Checking  -89.99 USD
      Expenses:Electronics:Audio  85.00 USD
        narration: "Bose QuietComfort 45"
      Expenses:Shopping:Shipping  4.99 USD
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from beancount import loader as bc_loader
from beancount.core import amount as bc_amount
from beancount.core import data
from beancount.parser import printer as bc_printer

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date as date_type
    from decimal import Decimal
    from pathlib import Path

__all__ = [
    "DEFAULT_PENDING_WINDOW_DAYS",
    "PendingPosting",
    "PendingTransaction",
    "enrich_from_pending",
    "load_pending_transactions",
    "match_pending_transaction",
    "remove_pending_transactions",
]

#: The default match window, in days.
DEFAULT_PENDING_WINDOW_DAYS = 4

_BEANCOUNT_INTERNAL_META = frozenset({"filename", "lineno"})


@dataclass(frozen=True, slots=True)
class PendingPosting:
    """One pre-defined posting split of a pending transaction.

    Attributes:
        account: The account.
        amount: The amount, or ``None`` to let Beancount balance it.
        metadata: The posting's metadata.
    """

    account: str
    amount: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PendingTransaction:
    """A one-time transaction pending posting and awaiting an import match.

    Attributes:
        date: The date the transaction was staged.
        account: The main account to match (the first posting).
        amount: The amount to match (exact).
        payee: The payee.
        narration: The narration.
        postings: The pre-defined posting splits.
        metadata: Additional transaction metadata.
        tags: The transaction's tags.
        links: The transaction's links.
        source: The file the pending transaction came from.
    """

    date: date_type
    account: str
    amount: Decimal
    payee: str
    narration: str
    postings: tuple[PendingPosting, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: frozenset[str] = frozenset()
    links: frozenset[str] = frozenset()
    source: Path | None = None


def load_pending_transactions(file_path: Path) -> list[PendingTransaction]:
    """Load the pending transactions from a Beancount file.

    The file is parsed with Beancount's ``auto_accounts`` plugin injected in
    memory, so accounts need not be opened, and the file on disk is untouched.

    Args:
        file_path: The pending Beancount file.

    Returns:
        The pending transactions, in file order.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        return []
    injected = 'plugin "beancount.plugins.auto_accounts"\n\n' + content
    entries, _errors, _options = bc_loader.load_string(injected)

    pending: list[PendingTransaction] = []
    for entry in entries:
        if not isinstance(entry, data.Transaction) or not entry.postings:
            continue
        first = entry.postings[0].units
        if first is None or first.number is None:
            continue
        postings = tuple(
            PendingPosting(
                account=posting.account,
                amount=posting.units.number if posting.units else None,
                metadata=_user_meta(posting.meta),
            )
            for posting in entry.postings
        )
        pending.append(
            PendingTransaction(
                date=entry.date,
                account=entry.postings[0].account,
                amount=first.number,
                payee=entry.payee or "",
                narration=entry.narration or "",
                postings=postings,
                metadata=_user_meta(entry.meta),
                tags=entry.tags or frozenset(),
                links=entry.links or frozenset(),
                source=file_path,
            )
        )
    return pending


def _user_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Return an entry or posting's metadata without Beancount's internals.

    Args:
        meta: The metadata, or ``None``.

    Returns:
        The user metadata.
    """
    return {
        key: value
        for key, value in (meta or {}).items()
        if key not in _BEANCOUNT_INTERNAL_META
    }


def match_pending_transaction(
    txn: data.Transaction,
    pending_transactions: Iterable[PendingTransaction],
    window_days: int = DEFAULT_PENDING_WINDOW_DAYS,
) -> PendingTransaction | None:
    """Match an imported transaction against the pending transactions.

    All of the account, the amount and the date window must match.

    Args:
        txn: The imported transaction.
        pending_transactions: The pending transactions to consider.
        window_days: The match window, in days.

    Returns:
        The matching pending transaction, or ``None``.
    """
    if not txn.postings or txn.postings[0].units is None:
        return None
    account = txn.postings[0].account
    amount = txn.postings[0].units.number
    for pending in pending_transactions:
        if pending.account != account or pending.amount != amount:
            continue
        if abs((txn.date - pending.date).days) <= window_days:
            return pending
    return None


def enrich_from_pending(
    txn: data.Transaction, pending: PendingTransaction
) -> data.Transaction:
    """Enrich an imported transaction with a pending template.

    Args:
        txn: The imported transaction.
        pending: The matched pending transaction.

    Returns:
        The enriched transaction.
    """
    meta = dict(txn.meta)
    meta.update(pending.metadata)
    first = txn.postings[0].units if txn.postings else None
    currency = first.currency if first is not None else "USD"
    postings = [
        data.Posting(
            account=posting.account,
            units=(
                None
                if posting.amount is None
                else bc_amount.Amount(posting.amount, currency)
            ),
            cost=None,
            price=None,
            flag=None,
            meta=dict(posting.metadata) or None,
        )
        for posting in pending.postings
    ]
    return txn._replace(
        meta=meta,
        payee=pending.payee or txn.payee,
        narration=pending.narration or txn.narration,
        tags=(txn.tags | pending.tags) - frozenset({"pending"}),
        links=txn.links | pending.links,
        postings=postings,
    )


def remove_pending_transactions(
    file_path: Path, matched: Iterable[PendingTransaction]
) -> None:
    """Remove matched pending transactions from the file.

    Args:
        file_path: The pending Beancount file.
        matched: The pending transactions to remove.
    """
    try:
        entries, _errors, _options = bc_loader.load_file(str(file_path))
    except OSError:
        return
    remove = {(item.date, item.payee, item.amount) for item in matched}
    kept = []
    for entry in entries:
        if isinstance(entry, data.Transaction):
            key = (
                entry.date,
                entry.payee,
                entry.postings[0].units.number
                if entry.postings and entry.postings[0].units
                else None,
            )
            if key in remove:
                continue
        kept.append(entry)
    with file_path.open("w", encoding="utf-8") as handle:
        for entry in kept:
            bc_printer.print_entry(entry, file=handle)
