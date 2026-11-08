"""The beangulp import hook: match, enrich and tag scheduled transactions.

The hook runs during a beangulp import. It loads the schedules **directly from
``Schedules.bean``** by path (config or environment), not from the import
ledger, so forecast entries the plugin may inject are never mistaken for
existing ones. It then matches the imported transactions against each rule's
outstanding nominal occurrences, greedily and chronologically, and tags a match
with ``schedule: "<id>"`` metadata.

The hook never writes a rule. Tagging is part of the entries it already
produces, so an aborted extract persists nothing. Pending transactions in
``pending.beancount`` are matched first, at higher priority, and removed from
their file once consumed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from beancount import loader as bc_loader
from beancount.core import amount as bc_amount
from beancount.core import data

from beanschedule import core
from beanschedule.pending import (
    PendingTransaction,
    enrich_from_pending,
    find_pending_file,
    load_pending_transactions,
    match_pending_transaction,
    remove_pending_transactions,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from beancount.core.data import Directive, Transaction

    from beanschedule.core import Rule, ScheduleResult, Split

__all__ = [
    "SCHEDULES_FILE",
    "find_schedules_file",
    "load_rules",
    "schedule_hook",
]

#: The file the hook loads the schedules from.
SCHEDULES_FILE = "Schedules.bean"

_ENV_SCHEDULES = "BEANSCHEDULE_SCHEDULES"

#: A beangulp import item: ``(filepath, entries, account, importer)``.
Extract = tuple[str, "list[Directive]", object, object]


@dataclass(frozen=True, slots=True)
class Match:
    """One imported transaction's resolution.

    Attributes:
        nominal: The nominal date it consumes.
        rule: The rule it resolves, or ``None`` for a pending match.
        split: Its amortization split, if any.
        pending: The pending transaction it resolves, if any.
    """

    nominal: date
    rule: Rule | None = None
    split: Split | None = None
    pending: PendingTransaction | None = None


def find_schedules_file() -> Path | None:
    """Find the ``Schedules.bean`` file.

    The path comes from the ``BEANSCHEDULE_SCHEDULES`` environment variable, or
    ``Schedules.bean`` in the current directory. The hook loads it directly,
    never from the import ledger, so injected forecast entries never look like
    existing ones.

    Returns:
        The path, or ``None`` when no schedules file is found.
    """
    if env_path := os.getenv(_ENV_SCHEDULES):
        path = Path(env_path)
        if path.is_file():
            return path
    default = Path(SCHEDULES_FILE)
    return default if default.is_file() else None


def load_rules(path: Path | None = None) -> list[Rule]:
    """Load the schedules file and return its rules.

    Args:
        path: The schedules file, or ``None`` to discover it.

    Returns:
        The rules, in declaration order, or an empty list when there is no
        schedules file.
    """
    resolved = path if path is not None else find_schedules_file()
    if resolved is None:
        return []
    entries, _errors, options = bc_loader.load_file(str(resolved))
    return list(core.compute(entries, options).rules)


def schedule_hook(
    extracted_entries_list: list[Extract],
    existing_entries: Sequence[Directive] | None,
) -> list[Extract]:
    """Match, enrich and tag imported transactions against the schedules.

    Args:
        extracted_entries_list: The beangulp import items.
        existing_entries: The existing ledger entries, so already-resolved
            occurrences are not matched again.

    Returns:
        The import items, with the matched transactions enriched and tagged.
    """
    schedules_path = find_schedules_file()
    if schedules_path is None:
        return extracted_entries_list
    schedule_entries, _errors, options = bc_loader.load_file(str(schedules_path))
    combined = list(schedule_entries) + list(existing_entries or [])
    result = core.compute(
        combined,
        options,
        today=date.today(),  # noqa: DTZ011 - reference date
    )
    rules = {rule.id: rule for rule in result.rules}
    if not rules:
        return extracted_entries_list

    pending_path = find_pending_file()
    pending = load_pending_transactions(pending_path) if pending_path else []
    consumed: list[PendingTransaction] = []

    matches = _match(extracted_entries_list, combined, result, rules, pending, consumed)
    enriched = _apply(extracted_entries_list, matches)
    if consumed and pending_path is not None:
        remove_pending_transactions(pending_path, consumed)
    return enriched


def _match(
    items: Sequence[Extract],
    combined: Sequence[Directive],
    result: ScheduleResult,
    rules: dict[str, Rule],
    pending: list[PendingTransaction],
    consumed: list[PendingTransaction],
) -> dict[int, Match]:
    """Decide which imported transactions resolve which occurrences.

    Pending transactions are matched first, at higher priority; a pending match
    records no schedule. The remaining transactions are then matched against
    each rule's outstanding occurrences with :func:`core.assign`.

    Args:
        items: The beangulp import items.
        combined: The existing ledger entries, for amortization.
        result: The computed schedule result over the existing ledger.
        rules: The rules, keyed by id, with windows applied.
        pending: The loaded pending transactions.
        consumed: Extended with the pending transactions that matched.

    Returns:
        A mapping from ``id(transaction)`` to its :data:`Match`.
    """
    remaining = [
        entry
        for _path, entries, _account, _importer in items
        for entry in entries
        if isinstance(entry, data.Transaction)
    ]
    pending_remaining = list(pending)
    matches: dict[int, Match] = {}

    unmatched: list[Transaction] = []
    for entry in remaining:
        pending_match = match_pending_transaction(entry, pending_remaining)
        if pending_match is None:
            unmatched.append(entry)
            continue
        consumed.append(pending_match)
        pending_remaining.remove(pending_match)
        matches[id(entry)] = Match(nominal=entry.date, pending=pending_match)
    remaining = unmatched

    balances = core.ledger_balances(combined, core.amortized_accounts(result))
    for rule in rules.values():
        report = result.report(rule.id)
        if report is None:
            continue
        outstanding = [o.nominal for o in report.occurrences if not o.resolved]
        if not outstanding:
            continue
        splits = (
            core.amortization_splits(rule, outstanding, combined, balances=balances)
            if rule.amortization is not None
            else {}
        )
        for link in core.assign(rule, outstanding, remaining):
            remaining.remove(link.transaction)
            matches[id(link.transaction)] = Match(
                nominal=link.nominal,
                rule=rule,
                split=splits.get(link.nominal),
            )
    return matches


def _apply(items: Sequence[Extract], matches: dict[int, Match]) -> list[Extract]:
    """Rewrite the matched transactions with their schedule.

    Args:
        items: The beangulp import items.
        matches: The matches, keyed by ``id(transaction)``.

    Returns:
        The import items with the matched transactions enriched.
    """
    out: list[Extract] = []
    for path, entries, account, importer in items:
        rewritten: list[Directive] = []
        for entry in entries:
            if not isinstance(entry, data.Transaction):
                rewritten.append(entry)
                continue
            match = matches.get(id(entry))
            if match is None:
                rewritten.append(entry)
                continue
            if match.pending is not None:
                rewritten.append(enrich_from_pending(entry, match.pending))
            elif match.rule is not None:
                rewritten.append(_enrich(entry, match.rule, match.split))
            else:
                rewritten.append(entry)
        out.append((path, rewritten, account, importer))
    return out


def _enrich(entry: Transaction, rule: Rule, split: Split | None) -> Transaction:
    """Tag and enrich one matched transaction.

    The matched posting keeps the imported amount; the schedule's payee and
    narration override the imported ones when set. An amortized rule rewrites
    the other side into its principal, interest and escrow accounts.

    Args:
        entry: The transaction.
        rule: The rule it resolves.
        split: Its amortization split, if any.

    Returns:
        The enriched transaction.
    """
    meta = dict(entry.meta)
    meta[core.SCHEDULE_KEY] = rule.id
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
        postings=postings,
    )


def _template_postings(entry: Transaction, rule: Rule) -> list[data.Posting]:
    """Build a matched transaction's postings from the rule's template.

    The matched posting keeps the imported amount; the rule's declared postings
    supply the other side, each with its amount and metadata. Every posting
    carries an explicit amount — a posting left for interpolation to fill would
    fail Beancount's balance check — so when a declared posting omits its amount
    it is filled to balance against the imported posting. A template that names
    more than one amount-less posting is unresolvable, and the imported postings
    are kept unchanged.

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
                meta=metadata or None,
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
        The postings: the matched cash posting, then the principal, interest
        and escrow accounts.
    """
    amort = rule.amortization
    currency = _currency(entry)
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
        postings.append(_posting(account, amount, currency))
    return postings


def _posting(account: str, amount: Decimal, currency: str) -> data.Posting:
    """Build a posting.

    Args:
        account: The account.
        amount: The amount.
        currency: The currency.

    Returns:
        The posting.
    """
    return data.Posting(
        account=account,
        units=bc_amount.Amount(amount, currency),
        cost=None,
        price=None,
        flag=None,
        meta=None,
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
