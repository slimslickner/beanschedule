"""Pure generation of ``custom "schedule"`` directives from schedule actions.

The CLI and the Fava report both change a schedule by appending, editing or
removing a single ``custom "schedule"`` directive. This module turns an action —
``new``, ``skip`` or ``move`` — into the Beancount directive that expresses it,
and renders it with Beancount's own printer, so the CLI and the web report emit
identical text. It performs no I/O and imports neither the CLI nor Fava.
"""

from __future__ import annotations

from datetime import date  # noqa: TC003 - used by doctests at runtime
from decimal import Decimal
from typing import TYPE_CHECKING

from beancount.core.data import Custom
from beancount.parser import printer
from beancount.parser.grammar import ValueType

from beanschedule.core import DEFAULT_WINDOW
from beanschedule.schema import TYPE

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from beanschedule.core import Rule

__all__ = [
    "TYPE",
    "from_rule",
    "move",
    "new",
    "posting",
    "render",
    "skip",
]

#: The quantum every monetary amount is rounded to before it is written.
_CENT = Decimal("0.01")


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


def _custom(
    day: date,
    values: Sequence[object],
    meta: Mapping[str, object] | None = None,
) -> Custom:
    """Build a ``custom "schedule"`` directive.

    Args:
        day: The directive's date.
        values: The values after the ``schedule`` type, starting with the verb.
        meta: The directive's metadata, or ``None``.

    Returns:
        The directive.
    """
    return Custom(
        meta=dict(meta) if meta else {},
        date=day,
        type=TYPE,
        values=[ValueType(value, type(value)) for value in values],
    )


def _rule_meta(  # noqa: C901, PLR0912, PLR0913 - the rule's fields share one builder
    *,
    rrule: str,
    start: date,
    match_account: str,
    end: date | None = None,
    payee: str | None = None,
    narration: str | None = None,
    match_payee: str | None = None,
    match_amount: Decimal | None = None,
    amount_mode: str | None = None,
    amount_tolerance: Decimal | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    window_before: int | None = None,
    window_after: int | None = None,
    method: str | None = None,
    rate: Decimal | None = None,
    term: int | None = None,
    escrow: Decimal | None = None,
    principal_account: str | None = None,
    interest_account: str | None = None,
    escrow_account: str | None = None,
) -> dict[str, object]:
    """Build a rule directive's metadata in the registry's key order.

    Args:
        rrule: The RFC 5545 recurrence rule.
        start: The first nominal date.
        match_account: The account an imported transaction must post to.
        end: The last nominal date, if any.
        payee: The payee to write onto enriched transactions.
        narration: The narration to write onto enriched transactions.
        match_payee: A payee regex, if any.
        match_amount: The reference amount, if any.
        amount_mode: The amount mode, if given.
        amount_tolerance: The approx-mode tolerance, if any.
        amount_min: The range-mode lower bound, if any.
        amount_max: The range-mode upper bound, if any.
        window_before: Days before a nominal date, if non-zero.
        window_after: Days after a nominal date, if non-zero.
        method: The amortization method, if any.
        rate: The amortization rate, if any.
        term: The amortization term, if any.
        escrow: The amortization escrow amount, if any.
        principal_account: The liability account, if any.
        interest_account: The interest expense account, if any.
        escrow_account: The escrow expense account, if any.

    Returns:
        The metadata, omitting the fields that are ``None`` (or a zero window).
    """
    meta: dict[str, object] = {"rrule": rrule, "start": start}
    if end is not None:
        meta["end"] = end
    if payee is not None:
        meta["payee"] = payee
    if narration is not None:
        meta["narration"] = narration
    meta["match-account"] = match_account
    if match_payee is not None:
        meta["match-payee"] = match_payee
    if match_amount is not None:
        meta["match-amount"] = _number(match_amount)
    if amount_mode is not None:
        meta["amount-mode"] = amount_mode
    for key, value in (
        ("amount-tolerance", amount_tolerance),
        ("amount-min", amount_min),
        ("amount-max", amount_max),
    ):
        if value is not None:
            meta[key] = _number(value)
    if window_before:
        meta["window-before"] = Decimal(window_before)
    if window_after:
        meta["window-after"] = Decimal(window_after)
    if method is not None:
        meta["method"] = method
    if rate is not None:
        meta["rate"] = rate
    if term is not None:
        meta["term"] = Decimal(term)
    if escrow is not None:
        meta["escrow"] = _number(escrow)
    meta.update(
        {
            key: value
            for key, value in (
                ("principal-account", principal_account),
                ("interest-account", interest_account),
                ("escrow-account", escrow_account),
            )
            if value is not None
        }
    )
    return meta


def new(  # noqa: PLR0913 - the rule's fields share one builder
    schedule_id: str,
    day: date,
    *,
    rrule: str,
    start: date,
    match_account: str,
    end: date | None = None,
    payee: str | None = None,
    narration: str | None = None,
    match_payee: str | None = None,
    match_amount: Decimal | None = None,
    amount_mode: str | None = None,
    amount_tolerance: Decimal | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    window_before: int | None = None,
    window_after: int | None = None,
    method: str | None = None,
    rate: Decimal | None = None,
    term: int | None = None,
    escrow: Decimal | None = None,
    principal_account: str | None = None,
    interest_account: str | None = None,
    escrow_account: str | None = None,
) -> Custom:
    """Build a ``new`` directive.

    Args:
        schedule_id: The schedule's identifier.
        day: The directive's date.
        rrule: The RFC 5545 recurrence rule.
        start: The first nominal date.
        match_account: The account an imported transaction must post to.
        end: The last nominal date, if any.
        payee: The payee to write onto enriched transactions.
        narration: The narration to write onto enriched transactions.
        match_payee: A payee regex, if any.
        match_amount: The reference amount, if any.
        amount_mode: The amount mode, if given.
        amount_tolerance: The approx-mode tolerance, if any.
        amount_min: The range-mode lower bound, if any.
        amount_max: The range-mode upper bound, if any.
        window_before: Days before a nominal date, if non-zero.
        window_after: Days after a nominal date, if non-zero.
        method: The amortization method, if any.
        rate: The amortization rate, if any.
        term: The amortization term, if any.
        escrow: The amortization escrow amount, if any.
        principal_account: The liability account, if any.
        interest_account: The interest expense account, if any.
        escrow_account: The escrow expense account, if any.

    Returns:
        The directive.

    Examples:
        >>> entry = new(
        ...     "paycheck",
        ...     date(2026, 1, 1),
        ...     rrule="FREQ=MONTHLY;BYMONTHDAY=15",
        ...     start=date(2026, 1, 15),
        ...     match_account="Assets:Bank",
        ... )
        >>> print(render(entry))
        2026-01-01 custom "schedule" "new" "paycheck"
          rrule: "FREQ=MONTHLY;BYMONTHDAY=15"
          start: 2026-01-15
          match-account: "Assets:Bank"
    """
    meta = _rule_meta(
        rrule=rrule,
        start=start,
        match_account=match_account,
        end=end,
        payee=payee,
        narration=narration,
        match_payee=match_payee,
        match_amount=match_amount,
        amount_mode=amount_mode,
        amount_tolerance=amount_tolerance,
        amount_min=amount_min,
        amount_max=amount_max,
        window_before=window_before,
        window_after=window_after,
        method=method,
        rate=rate,
        term=term,
        escrow=escrow,
        principal_account=principal_account,
        interest_account=interest_account,
        escrow_account=escrow_account,
    )
    return _custom(day, ["new", schedule_id], meta)


def posting(
    schedule_id: str,
    account: str,
    day: date,
    *,
    amount: Decimal | None = None,
    metadata: Mapping[str, object] | None = None,
) -> Custom:
    """Build a ``posting`` directive.

    Args:
        schedule_id: The schedule the posting belongs to.
        account: The other-side account.
        day: The directive's date. Its date is ignored by the engine; the
            occurrence's date is used.
        amount: The posting's signed amount, or ``None`` to let Beancount
            balance it.
        metadata: Any other posting metadata, copied verbatim (such as
            ``narration`` or ``contribution-year``).

    Returns:
        The directive.

    Examples:
        >>> entry = posting(
        ...     "paycheck",
        ...     "Expenses:Taxes:Federal",
        ...     date(2026, 1, 1),
        ...     amount=Decimal("600"),
        ...     metadata={"contribution-year": 2026},
        ... )
        >>> print(render(entry))
        2026-01-01 custom "schedule" "posting" "paycheck" "Expenses:Taxes:Federal"
          amount: 600.00
          contribution-year: 2026
    """
    meta: dict[str, object] = {}
    if amount is not None:
        meta["amount"] = _number(amount)
    if metadata:
        meta.update({key: _coerce(value) for key, value in metadata.items()})
    return _custom(day, ["posting", schedule_id, account], meta)


def _inferred_mode(match_amount: Decimal | None) -> str:
    """Return the amount mode a rule with no explicit mode implies.

    Args:
        match_amount: The reference amount, if any.

    Returns:
        ``"exact"`` when there is a reference amount, else ``"any"``.
    """
    return "any" if match_amount is None else "exact"


def from_rule(rule: Rule) -> list[Custom]:
    """Rebuild the directives for a parsed rule.

    Editing a rule rewrites its directives in place, so the recurring series
    (and therefore the nominal dates and their links) stays put. The ``new``
    directive comes first, then one ``posting`` directive per declared posting.

    Defaults are omitted, so a rule that never named a window or an amount mode
    is not rewritten with them: a canonical rebuild of an unchanged ledger is a
    no-op.

    Args:
        rule: The rule.

    Returns:
        The directives, the ``new`` first.
    """
    amort = rule.amortization
    meta = _rule_meta(
        rrule=rule.rrule,
        start=rule.start,
        match_account=rule.match_account,
        end=rule.end,
        payee=rule.payee,
        narration=rule.narration,
        match_payee=rule.match_payee,
        match_amount=rule.match_amount,
        amount_mode=(
            None
            if rule.amount_mode == _inferred_mode(rule.match_amount)
            else rule.amount_mode
        ),
        amount_tolerance=rule.amount_tolerance,
        amount_min=rule.amount_min,
        amount_max=rule.amount_max,
        window_before=(
            None if rule.window_before == DEFAULT_WINDOW else rule.window_before
        ),
        window_after=(
            None if rule.window_after == DEFAULT_WINDOW else rule.window_after
        ),
        method=amort.method if amort else None,
        rate=amort.rate if amort else None,
        term=amort.term if amort else None,
        escrow=amort.escrow if amort else None,
        principal_account=amort.principal_account if amort else None,
        interest_account=amort.interest_account if amort else None,
        escrow_account=amort.escrow_account if amort else None,
    )
    directives = [_custom(rule.declared, ["new", rule.id], meta)]
    directives.extend(
        posting(
            rule.id,
            spec.account,
            rule.declared,
            amount=spec.amount,
            metadata=spec.as_dict(),
        )
        for spec in rule.postings
    )
    return directives


def skip(schedule_id: str, nominal: date) -> Custom:
    """Build a ``skip`` directive.

    Args:
        schedule_id: The schedule whose occurrence is skipped.
        nominal: The skipped nominal date, which becomes the directive's date.

    Returns:
        The directive.

    Examples:
        >>> render(skip("paycheck", date(2026, 12, 15)))
        '2026-12-15 custom "schedule" "skip" "paycheck"'
    """
    return _custom(nominal, ["skip", schedule_id])


def move(schedule_id: str, nominal: date, new_date: date) -> Custom:
    """Build a ``move`` directive.

    Args:
        schedule_id: The schedule whose occurrence is moved.
        nominal: The original nominal date, which becomes the directive's date.
        new_date: The date the occurrence moves to.

    Returns:
        The directive.

    Examples:
        >>> render(move("paycheck", date(2026, 12, 15), date(2026, 12, 20)))
        '2026-12-15 custom "schedule" "move" "paycheck" 2026-12-20'
    """
    return _custom(nominal, ["move", schedule_id, new_date])


def render(entry: Custom) -> str:
    """Render a directive as it should appear in a ledger.

    Delegates to Beancount's own printer so the CLI and the Fava report never
    disagree on spelling.

    Args:
        entry: The directive.

    Returns:
        The directive's text, without a trailing newline.
    """
    return printer.format_entry(entry).rstrip("\n")
