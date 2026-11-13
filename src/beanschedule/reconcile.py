"""Post-import reconciliation of expected transactions against the ledger.

There is no import hook. Import runs normally; reconciliation is an explicit,
re-runnable step. This module is pure — it reads a ledger, a schedules file and
a pending file, and returns a :class:`Plan` describing which real transactions
resolve which expected ones, which schedule frontiers advance, and which
pending placeholders are consumed. The CLI and the Fava report render and apply
the plan; this module never touches disk.

The engine reuses :mod:`beanschedule.core`'s matching and amortization: a
schedule's outstanding occurrences (from its frontier forward) are linked to
candidate transactions greedily and chronologically, and each matched
transaction is enriched with the schedule's postings.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from beancount.core import amount as bc_amount
from beancount.core import data

from beanschedule import core, recurrence
from beanschedule.core import Rule, Split, compute
from beanschedule.pending import (
    PendingTransaction,
    enrich_from_pending,
    match_pending_transaction,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from beancount.core.data import Directive, Transaction

__all__ = [
    "Advance",
    "Match",
    "PendingMatch",
    "Plan",
    "enrich",
    "plan",
]

#: A transaction is recognised as pending by the file it came from.
_BEANCOUNT_META = frozenset({"filename", "lineno"})


@dataclass(frozen=True, slots=True)
class Match:
    """A real transaction resolving a schedule occurrence.

    Attributes:
        rule: The schedule it resolves.
        nominal: The nominal date it consumes.
        transaction: The real transaction.
        split: Its amortization split, if the schedule is amortized.
    """

    rule: Rule
    nominal: date
    transaction: Transaction
    split: Split | None = None


@dataclass(frozen=True, slots=True)
class PendingMatch:
    """A real transaction resolving a pending placeholder.

    Attributes:
        pending: The pending transaction it resolves.
        transaction: The real transaction.
    """

    pending: PendingTransaction
    transaction: Transaction


@dataclass(frozen=True, slots=True)
class Advance:
    """A schedule frontier moving to its next occurrence.

    Attributes:
        rule: The schedule.
        new_date: The next occurrence date, or ``None`` when the series has
            ended and the schedule should be removed.
    """

    rule: Rule
    new_date: date | None


@dataclass(frozen=True, slots=True)
class Plan:
    """Everything reconciliation would change in one pass.

    Attributes:
        matches: The schedule occurrences resolved.
        pending: The pending placeholders resolved.
        advances: The schedule frontiers to move.
    """

    matches: tuple[Match, ...]
    pending: tuple[PendingMatch, ...]
    advances: tuple[Advance, ...]

    @property
    def empty(self) -> bool:
        """Whether the plan changes nothing."""
        return not (self.matches or self.pending or self.advances)


def _pending_names(pending: Sequence[PendingTransaction]) -> set[str]:
    """Return the file names the pending transactions came from.

    Args:
        pending: The pending transactions.

    Returns:
        The basenames of their source files.
    """
    return {Path(str(item.source)).name for item in pending if item.source is not None}


def _is_pending_entry(entry: Transaction, names: set[str]) -> bool:
    """Report whether a transaction came from a pending file.

    Args:
        entry: The transaction.
        names: The pending files' basenames.

    Returns:
        ``True`` when the transaction's source file is a pending file.
    """
    filename = (entry.meta or {}).get("filename")
    return filename is not None and Path(str(filename)).name in names


def plan(
    entries: Sequence[Directive],
    schedules: Sequence[Directive],
    pending: Sequence[PendingTransaction] = (),
    options: Mapping[str, object] | None = None,
    *,
    today: date | None = None,
) -> Plan:
    """Build the reconciliation plan for a ledger.

    Args:
        entries: The main ledger entries.
        schedules: The schedule transactions.
        pending: The pending transactions to consume first.
        options: The Beancount options map, for amortization.
        today: The reference date, if any.

    Returns:
        The :class:`Plan`.
    """
    options = options or {}
    result = compute(entries, options, schedules=schedules, today=today)
    pending_names = _pending_names(pending)
    remaining = [
        entry
        for entry in entries
        if isinstance(entry, data.Transaction)
        and not core.is_schedule(entry)
        and core.schedule_id(entry) is None
        and not _is_pending_entry(entry, pending_names)
    ]

    pending_matches: list[PendingMatch] = []
    pool = list(pending)
    for entry in list(remaining):
        matched_pending = match_pending_transaction(entry, pool)
        if matched_pending is None:
            continue
        pool.remove(matched_pending)
        remaining.remove(entry)
        pending_matches.append(PendingMatch(matched_pending, entry))

    matches: list[Match] = []
    advances: list[Advance] = []
    balances = core.ledger_balances(entries, core.amortized_accounts(result))
    for rule in result.rules:
        report = result.report(rule.id)
        if report is None or not report.occurrences:
            continue
        outstanding = [o.nominal for o in report.occurrences if not o.resolved]
        nominal_dates = [o.nominal for o in report.occurrences]
        splits = (
            core.amortization_splits(
                rule,
                nominal_dates,
                entries,
                balances=balances,
                base=len(report.history),
            )
            if rule.amortization is not None
            else {}
        )
        linked: set[date] = set()
        for link in core.assign(rule, outstanding, remaining):
            remaining.remove(link.transaction)
            linked.add(link.nominal)
            matches.append(
                Match(rule, link.nominal, link.transaction, splits.get(link.nominal))
            )
        resolved = {o.nominal for o in report.occurrences if o.resolved} | linked
        unresolved = [day for day in nominal_dates if day not in resolved]
        new_date: date | None
        if unresolved:
            new_date = unresolved[0]
        else:
            new_date = recurrence.next_after(
                rule.rrule, rule.start, nominal_dates[-1], end=rule.end
            )
        if new_date != rule.start:
            advances.append(Advance(rule, new_date))

    return Plan(tuple(matches), tuple(pending_matches), tuple(advances))


# --- Enrichment ----------------------------------------------------------------


def enrich(match: Match) -> Transaction:
    """Return the enriched transaction a schedule match should become.

    Args:
        match: The match.

    Returns:
        The tagged and enriched transaction.
    """
    return _enrich(match.transaction, match.rule, match.split)


def enrich_pending(match: PendingMatch) -> Transaction:
    """Return the enriched transaction a pending match should become.

    Args:
        match: The pending match.

    Returns:
        The enriched transaction.
    """
    return enrich_from_pending(match.transaction, match.pending)


def _enrich(entry: Transaction, rule: Rule, split: Split | None) -> Transaction:
    """Tag and enrich one matched transaction.

    The matched posting keeps the imported amount; the schedule's payee and
    narration override the imported ones when set, and its tags, links and user
    metadata are carried onto the match. An amortized schedule rewrites the other
    side into its principal, interest and escrow accounts.

    Args:
        entry: The transaction.
        rule: The rule it resolves.
        split: Its amortization split, if any.

    Returns:
        The enriched transaction.
    """
    meta = dict(entry.meta or {})
    meta[core.SCHEDULE_KEY] = rule.id
    meta.update(rule.metadata)
    if split is not None:
        postings = _amortized_postings(entry, rule, split)
    elif rule.postings:
        postings = _template_postings(entry, rule)
    else:
        postings = entry.postings
    return entry._replace(
        meta=meta,
        payee=rule.payee or entry.payee,
        narration=rule.narration or entry.narration,
        tags=(entry.tags or frozenset()) | rule.tags,
        links=(entry.links or frozenset()) | rule.links,
        postings=postings,
    )


def _template_postings(entry: Transaction, rule: Rule) -> list[data.Posting]:
    """Build a matched transaction's postings from the schedule's split.

    Args:
        entry: The matched transaction.
        rule: The rule.

    Returns:
        The postings.
    """
    currency = _currency(entry)
    imported = [
        posting for posting in entry.postings if posting.account == rule.match_account
    ]
    imported_total = sum(
        (
            posting.units.number
            for posting in imported
            if posting.units is not None and posting.units.number is not None
        ),
        Decimal(0),
    )
    resolved = core.resolve_postings(rule.postings, -imported_total)
    if resolved is None:
        return list(entry.postings)
    return [
        *imported,
        *(
            data.Posting(
                account=account,
                units=bc_amount.Amount(value, currency),
                cost=None,
                price=None,
                flag=None,
                meta=dict(metadata) or None,
            )
            for account, value, metadata in resolved
        ),
    ]


def _amortized_postings(
    entry: Transaction, rule: Rule, split: Split
) -> list[data.Posting]:
    """Build an amortized transaction's postings.

    Args:
        entry: The matched transaction.
        rule: The rule.
        split: The amortization split.

    Returns:
        The postings: the matched posting, then the principal, interest and
        escrow accounts, each carrying its leg's declared metadata.
    """
    amort = rule.amortization
    currency = _currency(entry)
    metadata = {spec.account: dict(spec.metadata) for spec in rule.postings}
    postings = [
        posting for posting in entry.postings if posting.account == rule.match_account
    ]
    for account, amount in (
        (amort.principal_account if amort else None, split.principal),
        (amort.interest_account if amort else None, split.interest),
        (amort.escrow_account if amort else None, split.escrow),
    ):
        if account is None or amount == 0:
            continue
        postings.append(
            _posting(account, amount, currency, metadata.get(account) or None)
        )
    return postings


def _posting(
    account: str,
    amount: Decimal,
    currency: str,
    metadata: dict[str, object] | None = None,
) -> data.Posting:
    """Build a posting.

    Args:
        account: The account.
        amount: The amount.
        currency: The currency.
        metadata: The posting's metadata, if any.

    Returns:
        The posting.
    """
    return data.Posting(
        account=account,
        units=bc_amount.Amount(amount, currency),
        cost=None,
        price=None,
        flag=None,
        meta=metadata,
    )


def _currency(entry: Transaction) -> str:
    """Return the currency of a transaction's first amount.

    Args:
        entry: The transaction.

    Returns:
        The currency, defaulting to ``USD``.
    """
    for posting in entry.postings:
        if posting.units is not None:
            return posting.units.currency
    return "USD"
