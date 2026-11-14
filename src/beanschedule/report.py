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
from decimal import Decimal
from typing import TYPE_CHECKING

from beancount.core import compare

from beanschedule.core import (
    Diagnostic,
    Occurrence,
    Rule,
    ScheduleReport,
    ScheduleResult,
    Split,
    amortization_projection,
    amortization_splits,
    amortized_accounts,
    ledger_balances,
    matched_amount,
    operating_currency,
)
from beanschedule.schema import Severity

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from beancount.core.data import Directive, Transaction

__all__ = [
    "STATUS_DUE",
    "STATUS_MOVED",
    "STATUS_OVERDUE",
    "STATUS_POSTED",
    "STATUS_SKIPPED",
    "STATUS_UPCOMING",
    "AmortizationLine",
    "AmortizationView",
    "OccurrenceLine",
    "ScheduleRow",
    "ScheduleView",
    "ScheduleViewResult",
    "UpcomingLine",
    "build_view",
    "format_money",
    "format_payee",
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
#: The display status of an unresolved occurrence inside its match window.
STATUS_DUE = "due"

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
        due: Whether an unresolved occurrence is due — the reference date falls
            within the schedule's match window before its nominal date.
    """

    nominal: date
    effective: date
    status: str
    amount: Decimal | None = None
    payee: str | None = None
    narration: str | None = None
    entry_hash: str = ""
    split: Split | None = None
    due: bool = False

    @property
    def resolved(self) -> bool:
        """Whether a posted link, a skip or a move resolves the occurrence."""
        return self.status in (STATUS_POSTED, STATUS_SKIPPED, STATUS_MOVED)

    @property
    def pending(self) -> bool:
        """Whether the occurrence still needs attention (overdue or upcoming)."""
        return not self.resolved

    @property
    def display_status(self) -> str:
        """The canonical status word a report shows for the occurrence.

        A due occurrence reports :data:`STATUS_DUE` rather than its
        :data:`STATUS_UPCOMING` classification, so the badge says "due".

        Returns:
            The status word.
        """
        return STATUS_DUE if self.due else self.status


@dataclass(frozen=True, slots=True)
class UpcomingLine:
    """One occurrence in the cross-schedule upcoming ledger.

    Attributes:
        schedule_id: The schedule the occurrence belongs to.
        rule: The schedule's rule.
        line: The occurrence line.
    """

    schedule_id: str
    rule: Rule
    line: OccurrenceLine


@dataclass(frozen=True, slots=True)
class ScheduleRow:
    """One row of the Schedules table, shared by both scopes.

    Both the Upcoming scope (one row per outstanding occurrence) and the All
    scope (one row per schedule) render from this shape, so the two views agree
    on the columns, the payee/narration label and the schedule link.

    Attributes:
        schedule_id: The schedule the row belongs to.
        due: The row's date — the occurrence's nominal date, or the schedule's
            next occurrence — or ``None`` when a schedule has no next date.
        status: The canonical status word, or ``None`` for a blank status.
        payee: The payee, if any.
        narration: The narration, if any.
        amount: The amount expected on the posting account, if any.
        account: The schedule's matched (posting) account.
    """

    schedule_id: str
    due: date | None
    status: str | None
    payee: str | None
    narration: str | None
    amount: Decimal | None
    account: str

    @property
    def label(self) -> str:
        """The payee with the narration in parentheses, or whichever exists."""
        return format_payee(self.payee, self.narration)


@dataclass(frozen=True, slots=True)
class AmortizationLine:
    """One projected loan payment.

    Attributes:
        date: The nominal payment date.
        split: The payment's principal, interest and escrow split.
    """

    date: date
    split: Split

    @property
    def payment_number(self) -> int:
        """The one-based position in the series, or ``0`` when not meaningful."""
        return self.split.payment_number

    @property
    def principal(self) -> Decimal:
        """The principal component."""
        return self.split.principal

    @property
    def interest(self) -> Decimal:
        """The interest component."""
        return self.split.interest

    @property
    def escrow(self) -> Decimal:
        """The escrow component."""
        return self.split.escrow

    @property
    def payment(self) -> Decimal:
        """The principal-plus-interest payment, excluding escrow."""
        return self.split.principal + self.split.interest

    @property
    def total(self) -> Decimal:
        """The whole payment, including escrow."""
        return self.split.total

    @property
    def balance_after(self) -> Decimal:
        """The remaining principal after the payment."""
        return self.split.balance_after


@dataclass(frozen=True, slots=True)
class AmortizationView:
    """A loan's projected amortization to payoff.

    Attributes:
        method: ``"static"`` or ``"balance-from-ledger"``.
        rate: The annual interest rate.
        lines: The remaining payments, in date order.
    """

    method: str
    rate: Decimal
    lines: tuple[AmortizationLine, ...]

    @property
    def has_lines(self) -> bool:
        """Whether any payments remain to project."""
        return bool(self.lines)

    @property
    def remaining_payments(self) -> int:
        """How many payments remain."""
        return len(self.lines)

    @property
    def remaining_principal(self) -> Decimal:
        """The principal still to be paid."""
        return sum((line.principal for line in self.lines), Decimal(0))

    @property
    def remaining_interest(self) -> Decimal:
        """The interest still to be paid."""
        return sum((line.interest for line in self.lines), Decimal(0))

    @property
    def remaining_escrow(self) -> Decimal:
        """The escrow still to be paid."""
        return sum((line.escrow for line in self.lines), Decimal(0))

    @property
    def remaining_total(self) -> Decimal:
        """The total still to be paid, including escrow."""
        return sum((line.total for line in self.lines), Decimal(0))

    @property
    def payoff_date(self) -> date | None:
        """The date of the final projected payment, if any."""
        return self.lines[-1].date if self.lines else None


@dataclass(frozen=True, slots=True)
class ScheduleView:
    """A rule and its occurrences as a report shows them.

    Attributes:
        rule: The schedule's rule.
        rule_hash: The hash of the rule's ``new`` directive.
        lines: The occurrence lines in the view's window, ascending.
        next: The first unresolved nominal date, if any.
        overdue: The unresolved nominal dates strictly before the reference date.
        amortization: The loan's projected amortization to payoff, if amortized.
    """

    rule: Rule
    rule_hash: str
    lines: tuple[OccurrenceLine, ...]
    next: date | None
    overdue: tuple[date, ...]
    amortization: AmortizationView | None = None

    @property
    def id(self) -> str:
        """The schedule's identifier."""
        return self.rule.id

    @property
    def resolved(self) -> tuple[OccurrenceLine, ...]:
        """The resolved occurrence lines, oldest first — the schedule's ledger."""
        return tuple(line for line in self.lines if line.resolved)

    @property
    def posted(self) -> tuple[OccurrenceLine, ...]:
        """The posted occurrence lines, oldest first — the schedule's history.

        A skipped or moved occurrence leaves no trace in the ledger (the action
        advances the schedule's frontier), so history is what actually posted.
        """
        return tuple(line for line in self.lines if line.status == STATUS_POSTED)

    @property
    def upcoming(self) -> tuple[OccurrenceLine, ...]:
        """The unresolved future occurrence lines, soonest first."""
        return tuple(line for line in self.lines if line.status == STATUS_UPCOMING)

    @property
    def due(self) -> tuple[OccurrenceLine, ...]:
        """The unresolved occurrence lines that are due (within the match window)."""
        return tuple(line for line in self.lines if line.due)


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

    def rows(self, *, scope: str = "upcoming") -> tuple[ScheduleRow, ...]:
        """Build the Schedules table rows for a scope.

        Both scopes share this shape, so the template renders them the same way:
        ``"all"`` yields one row per schedule, anything else one row per
        outstanding occurrence (overdue, due and upcoming).

        Args:
            scope: ``"all"`` for one row per schedule; otherwise one row per
                outstanding occurrence.

        Returns:
            The rows.
        """
        if scope == "all":
            return tuple(_schedule_row(view) for view in self.schedules)
        return tuple(_occurrence_row(row) for row in self.ledger(pending_only=True))

    def ledger(self, *, pending_only: bool = False) -> tuple[UpcomingLine, ...]:
        """Flatten every schedule's occurrences into one date-ordered ledger.

        Args:
            pending_only: When ``True``, include only the unresolved occurrences
                (overdue, due and upcoming); otherwise include resolved ones too.

        Returns:
            The occurrence lines across all schedules, ascending by nominal date
            and then by schedule declaration order.
        """
        rows: list[UpcomingLine] = []
        for view in self.schedules:
            for line in view.lines:
                if pending_only and line.resolved:
                    continue
                rows.append(UpcomingLine(view.id, view.rule, line))
        rows.sort(key=lambda row: (row.line.nominal, row.line.status))
        return tuple(rows)


def today_month() -> date:
    """Return the first day of the current month.

    Returns:
        The first day of the local current month.

    Examples:
        >>> today_month().day
        1
    """
    return date.today().replace(day=1)  # noqa: DTZ011 - local today is intended


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


def format_payee(payee: str | None, narration: str | None) -> str:
    """Format a row's payee and narration into one label.

    Args:
        payee: The payee, if any.
        narration: The narration, if any.

    Returns:
        ``payee (narration)`` when both exist, whichever exists alone, or ``""``.

    Examples:
        >>> format_payee("Acme", "Paycheck")
        'Acme (Paycheck)'
        >>> format_payee("Acme", None)
        'Acme'
        >>> format_payee(None, "Paycheck")
        'Paycheck'
        >>> format_payee(None, None)
        ''
    """
    if payee and narration:
        return f"{payee} ({narration})"
    return payee or narration or ""


def _occurrence_row(upcoming: UpcomingLine) -> ScheduleRow:
    """Build a Schedules row from one outstanding occurrence.

    Args:
        upcoming: The upcoming ledger line.

    Returns:
        The :class:`ScheduleRow`.
    """
    line = upcoming.line
    rule = upcoming.rule
    return ScheduleRow(
        schedule_id=upcoming.schedule_id,
        due=line.nominal,
        status=line.display_status,
        payee=line.payee or rule.payee,
        narration=line.narration or rule.narration,
        amount=line.amount,
        account=rule.match_account,
    )


def _schedule_row(view: ScheduleView) -> ScheduleRow:
    """Build a Schedules row from one schedule.

    Args:
        view: The schedule view.

    Returns:
        The :class:`ScheduleRow`, with a status derived from the schedule.
    """
    rule = view.rule
    if view.overdue:
        status = STATUS_OVERDUE
    elif view.due:
        status = STATUS_DUE
    elif view.next is not None:
        status = STATUS_UPCOMING
    else:
        status = None
    return ScheduleRow(
        schedule_id=view.id,
        due=view.next,
        status=status,
        payee=rule.payee,
        narration=rule.narration,
        amount=rule.match_amount,
        account=rule.match_account,
    )


def _history_line(transaction: Transaction, rule: Rule) -> OccurrenceLine:
    """Build a report line from a resolved historical transaction.

    History is a real transaction that resolves an occurrence older than the
    schedule's window, so it is reported at its own date.

    Args:
        transaction: The resolved transaction.
        rule: The schedule's rule.

    Returns:
        The :class:`OccurrenceLine`.
    """
    return OccurrenceLine(
        nominal=transaction.date,
        effective=transaction.date,
        status=STATUS_POSTED,
        amount=matched_amount(transaction, rule.match_account),
        payee=transaction.payee,
        narration=transaction.narration,
        entry_hash=compare.hash_entry(transaction),
    )


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
    *,
    due: bool = False,
) -> OccurrenceLine:
    """Build a report line from a core occurrence.

    Args:
        occurrence: The core occurrence.
        status: Its classified status.
        rule: The schedule's rule.
        split: Its amortization split, if any.
        due: Whether the occurrence is due (within the match window).

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
            due=due,
        )
    entry: Directive | None = occurrence.entry
    return OccurrenceLine(
        nominal=occurrence.nominal,
        effective=occurrence.effective,
        status=status,
        amount=rule.match_amount if status == STATUS_OVERDUE else None,
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
    forecast_days: int | None = None,
) -> ScheduleViewResult:
    """Build the shared report view from a computed result.

    Args:
        result: The computed schedule result.
        entries: The ledger entries, for balance-from-ledger amortization.
        options: The Beancount options map, for the operating currency.
        today: The reference date for status and overdue, if any.
        forecast_months: How many months of future occurrences to include.
        forecast_days: How many days of future occurrences to include. When
            given it takes precedence over ``forecast_months``, giving an
            exact-day window rather than a whole-month one.

    Returns:
        The :class:`ScheduleViewResult`.
    """
    currency = operating_currency(options)
    balances = ledger_balances(entries, amortized_accounts(result))
    schedules: list[ScheduleView] = []
    for report in result.reports:
        rule = report.rule
        splits = amortization_splits(
            rule,
            [o.nominal for o in report.occurrences],
            entries,
            balances=balances,
            base=len(report.history),
        )
        horizon = (
            _horizon_days(today, forecast_days)
            if forecast_days is not None
            else _horizon(today, forecast_months)
        )
        lines: list[OccurrenceLine] = [
            _history_line(transaction, rule) for transaction in report.history
        ]
        for occurrence in report.occurrences:
            status = _status(occurrence, today)
            if (
                status == STATUS_UPCOMING
                and horizon is not None
                and occurrence.nominal > horizon
            ):
                continue
            due = status == STATUS_UPCOMING and _is_due(occurrence.nominal, rule, today)
            lines.append(
                _line(occurrence, status, rule, splits.get(occurrence.nominal), due=due)
            )
        schedules.append(
            ScheduleView(
                rule=rule,
                rule_hash=compare.hash_entry(rule.entry) if rule.entry else "",
                lines=tuple(lines),
                next=report.next,
                overdue=report.overdue,
                amortization=_amortization(report, entries, balances),
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


def _is_due(nominal: date, rule: Rule, today: date | None) -> bool:
    """Report whether an upcoming occurrence is due.

    An occurrence is due when the reference date has reached its match window —
    within ``window-before`` days of the nominal date — so a payment is expected
    now but has not posted yet.

    Args:
        nominal: The occurrence's nominal date.
        rule: The schedule's rule.
        today: The reference date, if any.

    Returns:
        ``True`` when the occurrence is due.
    """
    if today is None:
        return False
    return 0 <= (nominal - today).days <= rule.window_before


def _amortization(
    report: ScheduleReport,
    entries: Sequence[Directive],
    balances: Mapping[str, tuple[Decimal, date]],
) -> AmortizationView | None:
    """Project a schedule's remaining amortization to payoff.

    Args:
        report: The computed schedule report.
        entries: The ledger entries, for balance-from-ledger amortization.
        balances: A precomputed liability-balance index.

    Returns:
        The :class:`AmortizationView`, or ``None`` when the schedule is not
        amortized or its inputs are unavailable.
    """
    rule = report.rule
    amort = rule.amortization
    if amort is None:
        return None
    if amort.method == "static":
        if amort.term is None:
            return None
    elif amort.principal_account is None:
        return None
    pairs = amortization_projection(
        rule, base=len(report.history), entries=entries, balances=balances
    )
    lines = tuple(AmortizationLine(day, split) for day, split in pairs)
    return AmortizationView(amort.method, amort.rate, lines)


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


def _horizon_days(today: date | None, days: int) -> date | None:
    """Return the last date a view includes upcoming occurrences through.

    Unlike :func:`_horizon`, the window is an exact number of days rather than a
    whole number of months, so a two-week outlook ends on the day it names.

    Args:
        today: The reference date, if any.
        days: How many days forward.

    Returns:
        The horizon date, or ``None`` when there is no reference date.
    """
    return None if today is None else today + timedelta(days=days)
