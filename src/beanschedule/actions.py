"""Pure generation and rendering of schedule transactions.

The CLI and the Fava report both change a schedule by appending, editing or
removing a single transaction — the "frontier" transaction that carries the
schedule's metadata and its next occurrence date. This module turns an action
into that transaction and renders it with Beancount's own printer, so the CLI
and the web report emit identical text. It performs no I/O and imports neither
the CLI nor Fava.
"""

from __future__ import annotations

from datetime import date  # noqa: TC003 - used by doctests at runtime
from decimal import Decimal
from typing import TYPE_CHECKING

from beancount.core.amount import Amount
from beancount.core.data import Posting, Transaction
from beancount.parser import printer

from beanschedule.core import DEFAULT_WINDOW

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from beancount.core.data import Directive

    from beanschedule.core import Rule

__all__ = [
    "advance",
    "from_rule",
    "render",
    "schedule_transaction",
    "tag",
]

#: The quantum every monetary amount is rounded to before it is written.
_CENT = Decimal("0.01")

#: The leg names an amortized schedule may mark its postings with.
_LEG_ORDER = ("principal", "interest", "escrow")


def _number(value: Decimal | None) -> Decimal | None:
    """Round an amount to the cent.

    Args:
        value: The amount, or ``None``.

    Returns:
        The amount rounded to two decimal places, or ``None``.
    """
    return None if value is None else value.quantize(_CENT)


def _coerce(value: object) -> object:
    """Coerce a metadata value to something Beancount's printer renders.

    Beancount prints strings, decimals, dates, amounts and booleans, but not a
    bare Python ``int`` or ``float``, so those are widened to
    :class:`~decimal.Decimal`.

    Args:
        value: The metadata value.

    Returns:
        The value, widened when it is a bare number.
    """
    if isinstance(value, (bool, Decimal)):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    return value


def _posting(
    account: str,
    amount: Decimal | None,
    currency: str,
    metadata: Mapping[str, object] | None = None,
) -> Posting:
    """Build a posting.

    Args:
        account: The posting's account.
        amount: The signed amount, or ``None`` to let Beancount balance it.
        currency: The amount's currency.
        metadata: The posting's metadata, if any.

    Returns:
        The posting.
    """
    units = None if amount is None else Amount(amount.quantize(_CENT), currency)
    meta = {key: _coerce(value) for key, value in (metadata or {}).items()} or None
    return Posting(
        account=account,
        units=units,
        cost=None,
        price=None,
        flag=None,
        meta=meta,
    )


def schedule_transaction(  # noqa: PLR0913 - the schedule's fields share one builder
    schedule_id: str,
    day: date,
    *,
    rrule: str,
    match_account: str,
    currency: str = "USD",
    payee: str | None = None,
    narration: str | None = None,
    match_payee: str | None = None,
    match_amount: Decimal | None = None,
    amount_tolerance: Decimal | None = None,
    end: date | None = None,
    window_before: int | None = None,
    window_after: int | None = None,
    postings: Sequence[tuple[str, Decimal | None, Mapping[str, object] | None]] = (),
    tags: frozenset[str] = frozenset(),
    links: frozenset[str] = frozenset(),
    metadata: Mapping[str, object] | None = None,
) -> Transaction:
    """Build a schedule transaction.

    Args:
        schedule_id: The schedule's identifier.
        day: The transaction's date, which anchors the series and is its next
            occurrence.
        rrule: The RFC 5545 recurrence rule.
        match_account: The account an imported transaction must post to.
        currency: The operating currency.
        payee: The payee written onto enriched transactions.
        narration: The narration written onto enriched transactions.
        match_payee: A payee regex for matching, if any.
        match_amount: The matched posting's amount, if any.
        amount_tolerance: The approximate-match tolerance, if any.
        end: The last nominal date, if any.
        window_before: Days before a nominal date, if non-zero.
        window_after: Days after a nominal date, if non-zero.
        postings: The other-side postings as ``(account, amount, metadata)``.
        tags: The tags carried onto a matched transaction.
        links: The links carried onto a matched transaction.
        metadata: The user metadata carried onto a matched transaction.

    Returns:
        The transaction.

    Examples:
        >>> txn = schedule_transaction(
        ...     "paycheck",
        ...     date(2026, 1, 15),
        ...     rrule="FREQ=MONTHLY;BYMONTHDAY=15",
        ...     match_account="Assets:Bank",
        ...     payee="Acme",
        ...     match_amount=Decimal("-3000.00"),
        ...     postings=[
        ...         ("Expenses:Taxes", Decimal("600.00"), None),
        ...         ("Expenses:Savings", Decimal("2400.00"), None),
        ...     ],
        ... )
        >>> print(render(txn))
        2026-01-15 * "Acme" ""
          id: "paycheck"
          rrule: "FREQ=MONTHLY;BYMONTHDAY=15"
          match-account: "Assets:Bank"
          Assets:Bank       -3000.00 USD
          Expenses:Taxes      600.00 USD
          Expenses:Savings   2400.00 USD
    """
    meta: dict[str, object] = {"id": schedule_id, "rrule": rrule}
    meta["match-account"] = match_account
    if end is not None:
        meta["end"] = end
    if match_payee is not None:
        meta["match-payee"] = match_payee
    if amount_tolerance is not None:
        meta["amount-tolerance"] = _number(amount_tolerance)
    if window_before:
        meta["window-before"] = Decimal(window_before)
    if window_after:
        meta["window-after"] = Decimal(window_after)
    for key, value in (metadata or {}).items():
        meta[key] = _coerce(value)
    built = [_posting(match_account, match_amount, currency)]
    built.extend(
        _posting(account, amount, currency, metadata)
        for account, amount, metadata in postings
    )
    return Transaction(
        meta=meta,
        date=day,
        flag="*",
        payee=payee or "",
        narration=narration or "",
        tags=frozenset(tags),
        links=frozenset(links),
        postings=built,
    )


def from_rule(rule: Rule, currency: str = "USD") -> Transaction:
    """Rebuild the transaction for a parsed rule.

    Defaults are omitted, so a rule that never named a window or a tolerance is
    not rewritten with them: a canonical rebuild of an unchanged schedule is a
    no-op. Amortization legs keep their ``schedule-leg`` marker.

    Args:
        rule: The rule.
        currency: The operating currency.

    Returns:
        The schedule transaction.
    """
    legs: dict[str, str] = {}
    amort = rule.amortization
    if amort is not None:
        legs = {
            account: leg
            for leg, account in (
                ("principal", amort.principal_account),
                ("interest", amort.interest_account),
                ("escrow", amort.escrow_account),
            )
            if account is not None
        }
    postings: list[tuple[str, Decimal | None, dict[str, object] | None]] = []
    for spec in rule.postings:
        metadata = spec.as_dict()
        leg = legs.pop(spec.account, None)
        if leg is not None:
            metadata["schedule-leg"] = leg
        postings.append((spec.account, spec.amount, metadata or None))
    for account, leg in legs.items():
        postings.append((account, None, {"schedule-leg": leg}))
    meta_extra: dict[str, object] = {}
    if amort is not None:
        meta_extra["method"] = amort.method
        meta_extra["rate"] = amort.rate
        if amort.term is not None:
            meta_extra["term"] = Decimal(amort.term)
        if amort.escrow is not None:
            meta_extra["escrow"] = amort.escrow
    txn = schedule_transaction(
        rule.id,
        rule.start,
        rrule=rule.rrule,
        match_account=rule.match_account,
        currency=currency,
        payee=rule.payee,
        narration=rule.narration,
        match_payee=rule.match_payee,
        match_amount=rule.match_amount,
        amount_tolerance=rule.amount_tolerance,
        end=rule.end,
        window_before=(
            None if rule.window_before == DEFAULT_WINDOW else rule.window_before
        ),
        window_after=(
            None if rule.window_after == DEFAULT_WINDOW else rule.window_after
        ),
        postings=postings,
        tags=rule.tags,
        links=rule.links,
        metadata=dict(rule.metadata),
    )
    extra = {key: _coerce(value) for key, value in meta_extra.items()}
    return txn._replace(meta={**txn.meta, **extra})


def advance(rule: Rule, new_date: date, currency: str = "USD") -> Transaction:
    """Return the schedule transaction dated at its next occurrence.

    Args:
        rule: The rule.
        new_date: The next occurrence date.
        currency: The operating currency.

    Returns:
        The advanced transaction.
    """
    return from_rule(rule, currency)._replace(date=new_date)


def tag(entry: Transaction, schedule_id: str) -> Transaction:
    """Return a transaction tagged as resolving a schedule.

    Args:
        entry: The transaction.
        schedule_id: The schedule it resolves.

    Returns:
        The tagged transaction.
    """
    return entry._replace(meta={**(entry.meta or {}), "schedule": schedule_id})


def render(entry: Directive) -> str:
    """Render a directive as it should appear in a ledger.

    Delegates to Beancount's own printer so the CLI and the Fava report never
    disagree on spelling.

    Args:
        entry: The directive.

    Returns:
        The directive's text, without a trailing newline.
    """
    return printer.format_entry(entry).rstrip("\n")
