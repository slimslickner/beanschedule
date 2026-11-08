"""A neutral, read-only view of a computed schedule result.

Both the CLI and the Fava report render from :func:`build_view`, so the terminal
and the web page cannot disagree about a schedule's next occurrence, its overdue
occurrences or the transactions that resolved it. This module is pure: no I/O and
no Fava or CLI imports. The one exception is :func:`today_month`, which reads the
wall clock to pick a default month — a display concern the CLI and the Fava
report share from here rather than each reimplement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from beancount.core import compare

from beanschedule.core import (
    Diagnostic,
    Occurrence,
    Rule,
    ScheduleResult,
    Split,
    amortization_splits,
    amortized_accounts,
    ledger_balances,
    matched_amount,
)
from beanschedule.schema import Severity

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from decimal import Decimal

    from beancount.core.data import Directive

__all__ = [
    "STATUS_MOVED",
    "STATUS_OVERDUE",
    "STATUS_POSTED",
    "STATUS_SKIPPED",
    "STATUS_UPCOMING",
    "OccurrenceLine",
    "ScheduleView",
    "ScheduleViewResult",
    "build_view",
    "format_money",
    "operating_currency",
    "today_month",
]

#: The status of a posted occurrence, resolved by a transaction.
STATUS_POSTED = "posted"
#: The status of an occurrence resolved by a ``skip`` directive.
STATUS_SKIPPED = "skipped"
#: The status of an occurrence resolved by a ``move`` directive.
STATUS_MOVED = "moved"
#: The status of a nominal occurrence past due with no resolution.
STATUS_OVERDUE = "overdue"
#: The status of a future nominal occurrence with no resolution.
STATUS_UPCOMING = "upcoming"

#: How many months of future occurrences a view shows by default.
DEFAULT_FORECAST_MONTHS = 3


@dataclass(frozen=True, slots=True)
class OccurrenceLine:
    """One occurrence as a report shows it.

    Attributes:
        nominal: The nominal date the rule generates.
        effective: The date it lands on: a move target, the posted date, or the
            nominal date itself.
        status: One of :data:`STATUS_POSTED`, :data:`STATUS_SKIPPED`,
            :data:`STATUS_MOVED`, :data:`STATUS_OVERDUE` or
            :data:`STATUS_UPCOMING`.
        amount: The matched amount, for a posted occurrence, or the expected
            ``match-amount`` for an upcoming one, otherwise ``None``.
        payee: The linked transaction's payee, if any.
        narration: The linked transaction's narration, if any.
        entry_hash: The hash of the linked transaction or resolving directive, or
            ``""`` when the occurrence is unresolved.
        split: The amortization split for the occurrence, if any.
    """

    nominal: date
    effective: date
    status: str
    amount: Decimal | None = None
    payee: str | None = None
    narration: str | None = None
    entry_hash: str = ""
    split: Split | None = None

    @property
    def resolved(self) -> bool:
        """Whether a posted link, a skip or a move resolves the occurrence."""
        return self.status in (STATUS_POSTED, STATUS_SKIPPED, STATUS_MOVED)


@dataclass(frozen=True, slots=True)
class ScheduleView:
    """A rule and its occurrences as a report shows them.

    Attributes:
        rule: The schedule's rule.
        rule_hash: The hash of the rule's ``new`` directive.
        lines: The occurrence lines in the view's window, ascending.
        next: The first unresolved nominal date, if any.
        overdue: The unresolved nominal dates strictly before the reference date.
    """

    rule: Rule
    rule_hash: str
    lines: tuple[OccurrenceLine, ...]
    next: date | None
    overdue: tuple[date, ...]

    @property
    def id(self) -> str:
        """The schedule's identifier."""
        return self.rule.id

    @property
    def resolved(self) -> tuple[OccurrenceLine, ...]:
        """The resolved occurrence lines, oldest first — the schedule's ledger."""
        return tuple(line for line in self.lines if line.resolved)

    @property
    def upcoming(self) -> tuple[OccurrenceLine, ...]:
        """The unresolved future occurrence lines, soonest first."""
        return tuple(line for line in self.lines if line.status == STATUS_UPCOMING)


@dataclass(frozen=True, slots=True)
class ScheduleViewResult:
    """The rendered-ready view of every schedule.

    Attributes:
        currency: The operating currency.
        schedules: One :class:`ScheduleView` per rule, in declaration order.
        errors: The errors from the computation.
        warnings: The warnings from the computation.
    """

    currency: str
    schedules: tuple[ScheduleView, ...]
    errors: tuple[Diagnostic, ...]
    warnings: tuple[Diagnostic, ...]

    def schedule(self, schedule_id: str) -> ScheduleView | None:
        """Return a schedule view by id.

        Args:
            schedule_id: The schedule's identifier.

        Returns:
            The matching view, or ``None``.
        """
        return next((view for view in self.schedules if view.id == schedule_id), None)


def today_month() -> date:
    """Return the first day of the current month.

    Returns:
        The first day of the local current month.

    Examples:
        >>> today_month().day
        1
    """
    return date.today().replace(day=1)  # noqa: DTZ011 - local today is intended


def operating_currency(options: Mapping[str, object]) -> str:
    """Read the single operating currency from the ledger options.

    Args:
        options: The Beancount options map.

    Returns:
        The operating currency, or ``""`` when it is missing or ambiguous.

    Examples:
        >>> operating_currency({"operating_currency": "USD"})
        'USD'
        >>> operating_currency({})
        ''
    """
    value = options.get("operating_currency")
    if isinstance(value, str):
        return value
    if isinstance(value, list | tuple) and len(value) == 1:
        return str(value[0])
    return ""


def format_money(value: Decimal | None, currency: str = "") -> str:
    """Format an optional amount for a report line.

    Args:
        value: The amount, or ``None``.
        currency: The operating currency, appended when given.

    Returns:
        The amount as ``0.00`` with the currency appended, or ``-``.

    Examples:
        >>> from decimal import Decimal
        >>> format_money(Decimal("12.5"), "USD")
        '12.50 USD'
        >>> format_money(None)
        '-'
    """
    if value is None:
        return "-"
    text = f"{value:.2f}"
    return f"{text} {currency}" if currency else text


def _status(occurrence: Occurrence, today: date | None) -> str:
    """Classify an occurrence's status.

    Args:
        occurrence: The core occurrence.
        today: The reference date, if any.

    Returns:
        The status string.
    """
    if occurrence.posted is not None:
        return STATUS_POSTED
    if occurrence.moved_to is not None:
        return STATUS_MOVED
    if occurrence.skipped:
        return STATUS_SKIPPED
    if today is not None and occurrence.nominal < today:
        return STATUS_OVERDUE
    return STATUS_UPCOMING


def _line(
    occurrence: Occurrence,
    status: str,
    rule: Rule,
    split: Split | None,
) -> OccurrenceLine:
    """Build a report line from a core occurrence.

    Args:
        occurrence: The core occurrence.
        status: Its classified status.
        rule: The schedule's rule.
        split: Its amortization split, if any.

    Returns:
        The :class:`OccurrenceLine`.
    """
    posted = occurrence.posted
    if posted is not None:
        return OccurrenceLine(
            nominal=occurrence.nominal,
            effective=posted.date,
            status=status,
            amount=matched_amount(posted, rule.match_account),
            payee=posted.payee,
            narration=posted.narration,
            entry_hash=compare.hash_entry(posted),
            split=split,
        )
    if status == STATUS_UPCOMING:
        return OccurrenceLine(
            nominal=occurrence.nominal,
            effective=occurrence.nominal,
            status=status,
            amount=rule.match_amount,
            split=split,
        )
    entry: Directive | None = occurrence.entry
    return OccurrenceLine(
        nominal=occurrence.nominal,
        effective=occurrence.effective,
        status=status,
        entry_hash=compare.hash_entry(entry) if entry is not None else "",
        split=split,
    )


def build_view(
    result: ScheduleResult,
    entries: Sequence[Directive],
    options: Mapping[str, object],
    *,
    today: date | None = None,
    forecast_months: int = DEFAULT_FORECAST_MONTHS,
) -> ScheduleViewResult:
    """Build the shared report view from a computed result.

    Args:
        result: The computed schedule result.
        entries: The ledger entries, for balance-from-ledger amortization.
        options: The Beancount options map, for the operating currency.
        today: The reference date for status and overdue, if any.
        forecast_months: How many months of future occurrences to include.

    Returns:
        The :class:`ScheduleViewResult`.
    """
    currency = operating_currency(options)
    balances = ledger_balances(entries, amortized_accounts(result))
    schedules: list[ScheduleView] = []
    for report in result.reports:
        rule = report.rule
        splits = amortization_splits(
            rule, [o.nominal for o in report.occurrences], entries, balances=balances
        )
        horizon = _horizon(today, forecast_months)
        lines: list[OccurrenceLine] = []
        for occurrence in report.occurrences:
            status = _status(occurrence, today)
            if (
                status == STATUS_UPCOMING
                and horizon is not None
                and occurrence.nominal > horizon
            ):
                continue
            lines.append(
                _line(occurrence, status, rule, splits.get(occurrence.nominal))
            )
        schedules.append(
            ScheduleView(
                rule=rule,
                rule_hash=compare.hash_entry(rule.entry) if rule.entry else "",
                lines=tuple(lines),
                next=report.next,
                overdue=report.overdue,
            )
        )
    errors = tuple(d for d in result.diagnostics if d.severity is Severity.ERROR)
    warnings = tuple(d for d in result.diagnostics if d.severity is Severity.WARNING)
    return ScheduleViewResult(
        currency=currency,
        schedules=tuple(schedules),
        errors=errors,
        warnings=warnings,
    )


def _horizon(today: date | None, months: int) -> date | None:
    """Return the last date a view includes upcoming occurrences through.

    Args:
        today: The reference date, if any.
        months: How many months forward.

    Returns:
        The horizon date, or ``None`` when there is no reference date.
    """
    if today is None:
        return None
    index = today.year * 12 + (today.month - 1) + months
    first_next = date(index // 12, index % 12 + 1, 1)
    return first_next - timedelta(days=1)
