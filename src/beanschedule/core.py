"""Pure scheduled-transaction computation over a parsed Beancount ledger.

This module performs no I/O and imports neither the CLI nor Fava. It converts
Beancount entries into the engine's own typed records, parses the
``custom "schedule"`` directives, derives each rule's nominal occurrences,
resolves them against the transactions, skips and moves already in the ledger,
and reports diagnostics.

The model is iCalendar's, over Beancount directives:

* a **rule** is one immutable ``custom "schedule" "new"`` directive;
* a **posted occurrence** is a transaction whose ``schedule`` metadata names a
  rule — its nominal date is re-derived by the nearest-occurrence rule, so no
  actual or nominal date is stored on it;
* a **skip** is ``custom "schedule" "skip" "<id>"`` dated at the skipped nominal
  date (an EXDATE);
* a **move** is ``custom "schedule" "move" "<id>" <new_date>`` dated at the
  original nominal date (a RECURRENCE-ID);
* **``next``** is the first nominal date with no resolved occurrence, derived and
  never written.

Only the adapter helpers at the top of the module know about Beancount's types;
everything below them works on the engine's own records.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from beancount.core.amount import Amount
from beancount.core.data import Custom, Directive, Transaction

from beanschedule import recurrence
from beanschedule.schema import TYPE, Severity, get_diagnostic, render_message

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "AMOUNT_MODES",
    "DEFAULT_WINDOW",
    "METHODS",
    "SCHEDULE_KEY",
    "Amortization",
    "Diagnostic",
    "Link",
    "Occurrence",
    "PostingSpec",
    "Rule",
    "ScheduleReport",
    "ScheduleResult",
    "Source",
    "Split",
    "amortized_accounts",
    "assign",
    "compute",
    "format_amount",
    "ledger_balance",
    "ledger_balances",
    "matched_amount",
    "nearest_nominal",
    "resolve_nominal",
    "resolve_postings",
]

#: The transaction metadata key that links a posted occurrence to its rule.
SCHEDULE_KEY = "schedule"

#: The pre-2.0 metadata key, still accepted while a ledger is migrated.
LEGACY_SCHEDULE_KEY = "schedule_id"

#: The recognised amount modes.
AMOUNT_MODES = ("exact", "approx", "range", "any")

#: The recognised amortization methods.
METHODS = ("static", "balance-from-ledger")

#: How far past the reference date a series is expanded when finding ``next``.
_HORIZON = timedelta(days=366 * 5)

#: The radius searched either side of a date to re-derive a nominal date.
_RADIUS = timedelta(days=400)

#: The window a rule uses when it names neither ``window-before`` nor
#: ``window-after``.
DEFAULT_WINDOW = 3

#: The half-gap a lone (unbracketed) occurrence uses, so the window bounds it.
_OPEN_GAP = 10_000

_CENT = Decimal("0.01")
_MONTHS_PER_YEAR = 12


# --- Records -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Source:
    """A location in the ledger.

    Attributes:
        filename: The ledger file name.
        lineno: The one-based line number.
    """

    filename: str
    lineno: int


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A validation error or warning produced by the core.

    Attributes:
        code: The registered code, such as ``E001`` or ``W001``.
        severity: Whether the code is an error or a warning.
        message: The rendered, human-readable message.
        entry: The Beancount directive the diagnostic refers to, if any.
        source: A ledger location, when no directive is available.
    """

    code: str
    severity: Severity
    message: str
    entry: Directive | None = None
    source: Source | None = None


@dataclass(frozen=True, slots=True)
class Amortization:
    """A loan-payment split configuration.

    Attributes:
        method: ``"static"`` or ``"balance-from-ledger"``.
        rate: The annual interest rate, e.g. ``Decimal("0.0675")``.
        term: The term in whole months, for the static method.
        escrow: A fixed escrow amount added to each payment, if any.
        principal_account: The liability account holding the principal.
        interest_account: The expense account the interest posts to.
        escrow_account: The expense account the escrow posts to.
    """

    method: str
    rate: Decimal
    term: int | None = None
    escrow: Decimal | None = None
    principal_account: str | None = None
    interest_account: str | None = None
    escrow_account: str | None = None


@dataclass(frozen=True, slots=True)
class PostingSpec:
    """One declared other-side posting of a schedule.

    Attributes:
        account: The posting's account.
        amount: The signed amount, or ``None`` when Beancount should balance the
            posting.
        metadata: The posting's metadata, copied verbatim from the directive
            except for the reserved ``amount`` key.
        entry: The source directive, excluded from equality.
    """

    account: str
    amount: Decimal | None = None
    metadata: tuple[tuple[str, object], ...] = ()
    entry: Directive | None = field(default=None, compare=False, repr=False)

    def as_dict(self) -> dict[str, object]:
        """Return the posting's metadata as a mapping.

        Returns:
            The metadata, in declaration order.

        Examples:
            >>> PostingSpec("Expenses:X", Decimal("1"), (("narration", "Rent"),)).as_dict()
            {'narration': 'Rent'}
        """
        return dict(self.metadata)


@dataclass(frozen=True, slots=True)
class Rule:
    """One immutable schedule rule.

    Attributes:
        id: The schedule's stable identifier.
        declared: The directive's date.
        rrule: The RFC 5545 recurrence rule, without a ``DTSTART``.
        start: The first nominal date, anchoring the interval phase.
        end: The last nominal date, inclusive, if any.
        match_account: The account an imported transaction must post to.
        match_payee: A case-insensitive regex the payee must match, if any.
        match_amount: The reference amount for the amount mode, if any.
        amount_mode: ``"exact"``, ``"approx"``, ``"range"`` or ``"any"``.
        amount_tolerance: The ± bound for the approx mode, if any.
        amount_min: The lower bound for the range mode, if any.
        amount_max: The upper bound for the range mode, if any.
        window_before: Days before a nominal date a transaction may post.
        window_after: Days after a nominal date a transaction may post.
        payee: The payee written onto enriched transactions, if any.
        narration: The narration written onto enriched transactions, if any.
        postings: The other-side postings, in declaration order.
        amortization: The loan-split configuration, if any.
        entry: The source directive, excluded from equality.
    """

    id: str
    declared: date
    rrule: str
    start: date
    end: date | None
    match_account: str
    match_payee: str | None
    match_amount: Decimal | None
    amount_mode: str
    amount_tolerance: Decimal | None
    amount_min: Decimal | None
    amount_max: Decimal | None
    window_before: int
    window_after: int
    payee: str | None = None
    narration: str | None = None
    postings: tuple[PostingSpec, ...] = ()
    amortization: Amortization | None = None
    entry: Directive | None = field(default=None, compare=False, repr=False)

    @property
    def accounts(self) -> tuple[str, ...]:
        """The other-side posting accounts, in declaration order."""
        return tuple(posting.account for posting in self.postings)

    def nominal_dates(
        self, *, after: date | None = None, until: date | None = None
    ) -> list[date]:
        """List the rule's nominal dates within a window.

        Args:
            after: The earliest date to include, inclusive.
            until: The latest date to include, inclusive.

        Returns:
            The nominal dates, ascending.
        """
        return recurrence.occurrences(
            self.rrule, self.start, after=after, until=until, end=self.end
        )


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One nominal occurrence and the outcome that resolved it, if any.

    Attributes:
        rule_id: The schedule the occurrence belongs to.
        nominal: The nominal date the rule generates.
        posted: The transaction whose ``schedule`` metadata claims it, if any.
        skipped: Whether a ``skip`` directive resolves it.
        moved_to: The date a ``move`` directive moves it to, if any.
        entry: The ``skip`` or ``move`` directive that resolved it, if any.
    """

    rule_id: str
    nominal: date
    posted: Transaction | None = field(default=None, compare=False, repr=False)
    skipped: bool = False
    moved_to: date | None = None
    entry: Directive | None = field(default=None, compare=False, repr=False)

    @property
    def resolved(self) -> bool:
        """Whether a posted link, a skip or a move resolves the occurrence."""
        return self.posted is not None or self.skipped or self.moved_to is not None

    @property
    def effective(self) -> date:
        """The date the occurrence lands on: the move target or the posted date."""
        if self.moved_to is not None:
            return self.moved_to
        if self.posted is not None:
            return self.posted.date
        return self.nominal


@dataclass(frozen=True, slots=True)
class ScheduleReport:
    """A rule and its occurrences over the computed window.

    Attributes:
        rule: The schedule's rule.
        occurrences: The occurrences within the window, ascending.
        next: The first nominal date with no resolved occurrence, if any.
        overdue: The unresolved nominal dates strictly before the reference date.
    """

    rule: Rule
    occurrences: tuple[Occurrence, ...]
    next: date | None
    overdue: tuple[date, ...]

    @property
    def id(self) -> str:
        """The schedule's identifier."""
        return self.rule.id

    def occurrence(self, nominal: date) -> Occurrence | None:
        """Return the occurrence for a nominal date, if it is in the window.

        Args:
            nominal: The nominal date.

        Returns:
            The matching occurrence, or ``None``.
        """
        index = _occurrence_index(self.occurrences, nominal)
        return None if index is None else self.occurrences[index]


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    """The full outcome of a computation.

    Attributes:
        rules: The parsed rules, in declaration order.
        reports: One report per rule, in declaration order.
        diagnostics: Every error and warning, sorted deterministically.
    """

    rules: tuple[Rule, ...]
    reports: tuple[ScheduleReport, ...]
    diagnostics: tuple[Diagnostic, ...]

    def rule(self, schedule_id: str) -> Rule | None:
        """Return a rule by id.

        Args:
            schedule_id: The schedule's identifier.

        Returns:
            The matching rule, or ``None``.
        """
        return next((rule for rule in self.rules if rule.id == schedule_id), None)

    def report(self, schedule_id: str) -> ScheduleReport | None:
        """Return a report by id.

        Args:
            schedule_id: The schedule's identifier.

        Returns:
            The matching report, or ``None``.
        """
        return next(
            (report for report in self.reports if report.id == schedule_id), None
        )


# --- Adapter helpers (the only Beancount-aware section) ------------------------


def _unwrap(value: object) -> object:
    """Unwrap a Beancount ``ValueType`` into its value.

    Args:
        value: A custom-directive value, possibly a ``ValueType``.

    Returns:
        The underlying value.
    """
    return getattr(value, "value", value)


def _meta(entry: Directive) -> dict[str, object]:
    """Return an entry's user metadata.

    Args:
        entry: Any Beancount directive.

    Returns:
        The metadata without Beancount's ``filename`` and ``lineno`` keys.
    """
    return {
        key: value
        for key, value in (entry.meta or {}).items()
        if key not in {"filename", "lineno"}
    }


def _source(entry: Directive | None) -> Source | None:
    """Return the ledger location of an entry.

    Args:
        entry: A directive, or ``None``.

    Returns:
        The :class:`Source`, or ``None`` when unavailable.
    """
    if entry is None or entry.meta is None:
        return None
    filename = entry.meta.get("filename")
    lineno = entry.meta.get("lineno")
    if filename is None or lineno is None:
        return None
    return Source(str(filename), int(lineno))


def _diag(code: str, *, entry: Directive | None = None, **fields: object) -> Diagnostic:
    """Build a diagnostic from the registry.

    Args:
        code: The registered diagnostic code.
        entry: The directive the diagnostic refers to, if any.
        **fields: Values for the message template.

    Returns:
        The constructed :class:`Diagnostic`.
    """
    return Diagnostic(
        code=code,
        severity=get_diagnostic(code).severity,
        message=render_message(code, **fields),
        entry=entry,
        source=_source(entry),
    )


def _sort_key(diagnostic: Diagnostic) -> tuple[object, ...]:
    """Return a deterministic sort key for a diagnostic.

    Args:
        diagnostic: The diagnostic.

    Returns:
        The key: errors before warnings, then code, file and line.
    """
    return (
        diagnostic.severity != Severity.ERROR,
        diagnostic.code,
        diagnostic.source.filename if diagnostic.source else "",
        diagnostic.source.lineno if diagnostic.source else 0,
    )


def _sorted(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Sort diagnostics deterministically.

    Args:
        diagnostics: The diagnostics to sort.

    Returns:
        The diagnostics, errors before warnings, then by code and location.
    """
    return sorted(diagnostics, key=_sort_key)


def _amount_number(units: Amount | None) -> Decimal | None:
    """Return the numeric part of an amount, when present.

    Args:
        units: A posting's units, or ``None``.

    Returns:
        The number, or ``None`` when there is no amount or no number.
    """
    if units is None or units.number is None:
        return None
    return units.number


def matched_amount(entry: Transaction, account: str) -> Decimal | None:
    """Return the amount a transaction posts to an account.

    Args:
        entry: The transaction.
        account: The account to look for.

    Returns:
        The first posting's amount to that account, or ``None``.
    """
    for posting in entry.postings:
        if posting.account == account:
            return _amount_number(posting.units)
    return None


def _schedule_id(entry: Directive) -> str | None:
    """Return the schedule a directive names, accepting the legacy key.

    Args:
        entry: The directive.

    Returns:
        The schedule id from ``schedule`` metadata, falling back to
        ``schedule_id``, or ``None``.
    """
    meta = entry.meta or {}
    value = meta.get(SCHEDULE_KEY, meta.get(LEGACY_SCHEDULE_KEY))
    return value if isinstance(value, str) else None


# --- Nominal-date helpers ------------------------------------------------------


def _shift(value: date, days: int) -> date:
    """Shift a date by a signed number of days, clamped to the range.

    A ledger may carry a date near ``date.min`` or ``date.max`` (a far-future
    ``open`` or ``custom`` directive), so a plain ``date ± timedelta`` can
    overflow. The result is clamped to the representable range instead.

    Args:
        value: The date to shift.
        days: The signed number of days.

    Returns:
        The shifted date, clamped to ``date.min``/``date.max``.
    """
    if days >= 0:
        delta = timedelta(days=days)
        limit = date.max - delta
        return date.max if value > limit else value + delta
    delta = timedelta(days=-days)
    limit = date.min + delta
    return date.min if value < limit else value - delta


def nearest_nominal(rule: Rule, when: date) -> date | None:
    """Return the rule's nominal date nearest a date.

    Args:
        rule: The rule.
        when: The reference date.

    Returns:
        The nearest nominal date within the series window, or ``None`` when the
        series generates none near ``when``.

    Examples:
        >>> from datetime import date
        >>> rule = Rule(
        ...     id="rent", declared=date(2026, 1, 1),
        ...     rrule="FREQ=MONTHLY;BYMONTHDAY=1", start=date(2026, 1, 1),
        ...     end=None, match_account="Assets:Bank", match_payee=None,
        ...     match_amount=None, amount_mode="any", amount_tolerance=None,
        ...     amount_min=None, amount_max=None, window_before=3, window_after=3,
        ... )
        >>> nearest_nominal(rule, date(2026, 3, 30))
        datetime.date(2026, 4, 1)
    """
    window = rule.nominal_dates(
        after=_shift(when, -_RADIUS.days), until=_shift(when, _RADIUS.days)
    )
    if not window:
        return None
    return min(window, key=lambda nominal: (abs((nominal - when).days), nominal))


def _in_window(rule: Rule, when: date) -> bool:
    """Report whether a date is within a rule's series window.

    A transaction a few days before ``start`` or after ``end`` still resolves;
    one beyond the match window either side does not.

    Args:
        rule: The rule.
        when: The transaction's date.

    Returns:
        ``True`` when ``when`` is within the window.
    """
    if when < rule.start and (rule.start - when).days > rule.window_before:
        return False
    return not (
        rule.end is not None
        and when > rule.end
        and (when - rule.end).days > rule.window_after
    )


def _nearest_in(nominals: Sequence[date], when: date, rule: Rule) -> date | None:
    """Return the nearest of a precomputed nominal list, within the window.

    The list is bisected rather than scanned, so resolving a posted transaction
    is O(log n) instead of expanding the rule around the date.

    Args:
        nominals: The rule's nominal dates, ascending.
        when: The transaction's date.
        rule: The rule, for its window.

    Returns:
        The nearest nominal date, or ``None`` when none is close enough.
    """
    if not nominals or not _in_window(rule, when):
        return None
    index = bisect_left(nominals, when)
    candidates = nominals[max(0, index - 1) : index + 1]
    return min(candidates, key=lambda nominal: (abs((nominal - when).days), nominal))


def resolve_nominal(rule: Rule, when: date) -> date | None:
    """Re-derive a posted transaction's nominal date.

    The nearest occurrence is used, so a transaction posted a few days early or
    late lands on the occurrence it was intended for. A date outside the rule's
    ``start``/``end`` window — beyond the match window either side — resolves to
    nothing.

    Args:
        rule: The rule.
        when: The transaction's date.

    Returns:
        The nominal date, or ``None`` when the rule generates none that close.

    Examples:
        >>> from datetime import date
        >>> rule = Rule(
        ...     id="rent", declared=date(2026, 1, 1),
        ...     rrule="FREQ=MONTHLY;BYMONTHDAY=15", start=date(2026, 1, 15),
        ...     end=None, match_account="Assets:Bank", match_payee=None,
        ...     match_amount=None, amount_mode="any", amount_tolerance=None,
        ...     amount_min=None, amount_max=None, window_before=3, window_after=3,
        ... )
        >>> resolve_nominal(rule, date(2026, 3, 17))
        datetime.date(2026, 3, 15)
    """
    if not _in_window(rule, when):
        return None
    return nearest_nominal(rule, when)


def _occurrence_index(occurrences: Sequence[Occurrence], nominal: date) -> int | None:
    """Return an occurrence's index by nominal date, or ``None``.

    Args:
        occurrences: The occurrences, ascending by nominal date.
        nominal: The nominal date to find.

    Returns:
        The index, or ``None`` when the date is not present.
    """
    index = bisect_left(occurrences, nominal, key=lambda item: item.nominal)
    if index < len(occurrences) and occurrences[index].nominal == nominal:
        return index
    return None


def format_amount(value: Decimal, currency: str = "") -> str:
    """Format an amount for a diagnostic message.

    Args:
        value: The amount.
        currency: The currency code, appended when non-empty.

    Returns:
        The amount with two decimal places, and the currency if given.

    Examples:
        >>> from decimal import Decimal
        >>> format_amount(Decimal("-500"), "USD")
        '-500.00 USD'
        >>> format_amount(Decimal("0"))
        '0.00'
    """
    text = f"{value:.2f}"
    return f"{text} {currency}" if currency else text


# --- Matching ------------------------------------------------------------------


def _within_window(rule: Rule, when: date, nominal: date) -> bool:
    """Report whether a transaction date is within a rule's window.

    Args:
        rule: The rule.
        when: The transaction date.
        nominal: The nominal date.

    Returns:
        ``True`` when ``when`` is within ``window_before``/``window_after``.
    """
    offset = (when - nominal).days
    return -rule.window_before <= offset <= rule.window_after


def _amount_gate(rule: Rule, value: Decimal | None) -> bool:  # noqa: PLR0911
    """Report whether an amount passes the rule's amount mode.

    Args:
        rule: The rule.
        value: The transaction amount, or ``None``.

    Returns:
        ``True`` when the amount is acceptable.
    """
    if rule.amount_mode == "any":
        return True
    if value is None:
        return False
    if rule.amount_mode == "exact":
        return rule.match_amount is not None and value == rule.match_amount
    if rule.amount_mode == "approx":
        if rule.match_amount is None or rule.amount_tolerance is None:
            return False
        return abs(value - rule.match_amount) <= rule.amount_tolerance
    if rule.amount_mode == "range":
        if rule.amount_min is None or rule.amount_max is None:
            return False
        return rule.amount_min <= value <= rule.amount_max
    return False


def _payee_gate(rule: Rule, payee: str | None) -> bool:
    """Report whether a payee passes the rule's payee pattern.

    Args:
        rule: The rule.
        payee: The transaction payee, or ``None``.

    Returns:
        ``True`` when the payee matches, or when no pattern is set.
    """
    if rule.match_payee is None:
        return True
    if not payee:
        return False
    import re  # noqa: PLC0415 - a cheap local import keeps the module head light

    try:
        return re.search(rule.match_payee, payee, re.IGNORECASE) is not None
    except re.error:
        return False


def eligible(rule: Rule, entry: Transaction) -> bool:
    """Report whether a transaction may be linked to a rule.

    The gate is account, payee and amount only; the date is judged separately by
    the consumption rule.

    Args:
        rule: The rule.
        entry: The candidate transaction.

    Returns:
        ``True`` when the transaction posts to the rule's account and passes its
        payee and amount hints.
    """
    if matched_amount(entry, rule.match_account) is None:
        return False
    if not _payee_gate(rule, entry.payee):
        return False
    return _amount_gate(rule, matched_amount(entry, rule.match_account))


def _half_gaps(nominals: Sequence[date]) -> list[int]:
    """Return the half-gap around each nominal date, in days.

    The half-gap is half the distance to the closer bracketing occurrence, so a
    transaction can never plausibly match two occurrences. An endpoint uses the
    one side it has.

    Args:
        nominals: The nominal dates, ascending.

    Returns:
        One integer per nominal, the days either side a transaction may fall.

    Examples:
        >>> _half_gaps([date(2026, 1, 1), date(2026, 1, 11), date(2026, 1, 31)])
        [5, 5, 10]
    """
    gaps: list[int] = []
    for index, nominal in enumerate(nominals):
        candidates: list[int] = []
        if index > 0:
            candidates.append((nominal - nominals[index - 1]).days)
        if index + 1 < len(nominals):
            candidates.append((nominals[index + 1] - nominal).days)
        gaps.append(min(candidates) // 2 if candidates else _OPEN_GAP)
    return gaps


def _consumable(
    nominals: Sequence[date], index: int, when: date, gaps: Sequence[int]
) -> bool:
    """Report whether a date is close enough to consume an occurrence.

    Args:
        nominals: The nominal dates, ascending.
        index: The occurrence's index.
        when: The transaction date.
        gaps: The half-gaps from :func:`_half_gaps`, aligned with ``nominals``.

    Returns:
        ``True`` when ``when`` is within the occurrence's half-gap.
    """
    return abs((when - nominals[index]).days) <= gaps[index]


def resolve_postings(
    postings: Sequence[PostingSpec], total: Decimal
) -> tuple[tuple[str, Decimal, dict[str, object]], ...] | None:
    """Resolve a posting template so its amounts sum to a total.

    At most one posting may omit its amount; it is filled with the remainder, so
    every posting ends up with an explicit amount. Beancount's balance check
    reads ``get_weight`` on each posting, so a posting left for interpolation to
    fill would not be safe to emit. More than one omitted amount makes the split
    ambiguous, and the template is unresolvable.

    Args:
        postings: The declared postings.
        total: The amount the postings' amounts must sum to.

    Returns:
        ``(account, amount, metadata)`` triples, or ``None`` when unresolvable.

    Examples:
        >>> specs = (
        ...     PostingSpec("Expenses:A", Decimal("60")),
        ...     PostingSpec("Expenses:B"),
        ... )
        >>> [(a, str(v)) for a, v, _ in resolve_postings(specs, Decimal("100"))]
        [('Expenses:A', '60'), ('Expenses:B', '40')]
        >>> resolve_postings((PostingSpec("X"), PostingSpec("Y")), Decimal("1")) is None
        True
    """
    missing = [index for index, spec in enumerate(postings) if spec.amount is None]
    if len(missing) > 1:
        return None
    explicit = sum(
        (spec.amount for spec in postings if spec.amount is not None), Decimal(0)
    )
    fill = total - explicit if missing else None
    return tuple(
        (spec.account, value, spec.as_dict())
        for index, spec in enumerate(postings)
        if (value := (fill if index in missing else spec.amount)) is not None
    )


@dataclass(frozen=True, slots=True)
class Link:
    """A transaction assigned to a nominal occurrence.

    Attributes:
        nominal: The nominal date it consumes.
        transaction: The transaction that consumes it.
    """

    nominal: date
    transaction: Transaction = field(compare=False, repr=False)


def assign(
    rule: Rule,
    nominals: Sequence[date],
    transactions: Sequence[Transaction],
) -> tuple[Link, ...]:
    """Link transactions to a rule's occurrences, greedily and chronologically.

    Occurrences are walked oldest to newest; each takes the closest unlinked
    eligible transaction whose date is within ½ the gap to the bracketing
    neighbouring occurrence, and each transaction links at most once. A payment
    beyond ½ a period from the oldest outstanding occurrence therefore consumes a
    later one and leaves the older occurrence overdue.

    Args:
        rule: The rule.
        nominals: The nominal dates to resolve, ascending.
        transactions: The candidate transactions.

    Returns:
        The links, in nominal-date order.
    """
    ordered = sorted(nominals)
    gaps = _half_gaps(ordered)
    remaining = sorted(
        (entry for entry in transactions if eligible(rule, entry)),
        key=lambda entry: entry.date,
    )
    links: list[Link] = []
    for index, nominal in enumerate(ordered):
        candidates = [
            entry
            for entry in remaining
            if _within_window(rule, entry.date, nominal)
            and _consumable(ordered, index, entry.date, gaps)
        ]
        if not candidates:
            continue
        chosen = min(
            candidates,
            key=lambda entry: (abs((entry.date - nominal).days), entry.date),
        )
        remaining.remove(chosen)
        links.append(Link(nominal=nominal, transaction=chosen))
    return tuple(links)


# --- Amortization --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Split:
    """A loan payment's principal, interest and escrow components.

    Attributes:
        payment_number: The one-based position in the series, or ``0`` when not
            meaningful (balance-from-ledger).
        principal: The principal component.
        interest: The interest component.
        escrow: The escrow component, if any.
        total: The whole payment.
        balance_after: The remaining principal after the payment.
    """

    payment_number: int
    principal: Decimal
    interest: Decimal
    escrow: Decimal
    total: Decimal
    balance_after: Decimal


def _monthly_rate(rate: Decimal) -> Decimal:
    """Return the monthly rate from an annual rate.

    Args:
        rate: The annual rate, e.g. ``Decimal("0.06")``.

    Returns:
        The monthly rate.
    """
    return rate / Decimal(_MONTHS_PER_YEAR)


def static_split(
    rule: Rule, payment_number: int, escrow: Decimal = Decimal(0)
) -> Split | None:
    """Compute a static amortization split for one payment.

    The principal is the present value of the whole series of payments, where the
    payment is the rule's ``match_amount`` and the series has ``term`` payments at
    the rule's ``rate``. Interest each period is the remaining balance at the
    monthly rate.

    Args:
        rule: The rule; its ``amortization`` must be static.
        payment_number: The one-based payment position.
        escrow: An extra escrow amount added on top of the payment.

    Returns:
        The :class:`Split`, or ``None`` when the rule cannot be amortized.

    Examples:
        >>> from datetime import date
        >>> amort = Amortization(method="static", rate=Decimal("0.06"), term=12)
        >>> rule = Rule(
        ...     id="loan", declared=date(2026, 1, 1), rrule="FREQ=MONTHLY",
        ...     start=date(2026, 1, 1), end=None, match_account="Assets:Bank",
        ...     match_payee=None, match_amount=Decimal("-86.53"), amount_mode="exact",
        ...     amount_tolerance=None, amount_min=None, amount_max=None,
        ...     window_before=3, window_after=3, amortization=amort,
        ... )
        >>> split = static_split(rule, 1)
        >>> split.principal > 0 and split.interest > 0
        True
    """
    amort = rule.amortization
    if amort is None or amort.term is None or rule.match_amount is None:
        return None
    if not 1 <= payment_number <= amort.term:
        return None
    payment = abs(rule.match_amount)
    monthly = _monthly_rate(amort.rate)
    balance = _present_value(payment, monthly, amort.term)
    if monthly == 0:
        principal = (balance / Decimal(amort.term)).quantize(_CENT)
        interest = Decimal(0)
    else:
        interest = (balance * monthly).quantize(_CENT)
        principal = (payment - interest).quantize(_CENT)
    balance_after = max(Decimal(0), (balance - principal).quantize(_CENT))
    if payment_number == amort.term:
        principal = balance.quantize(_CENT)
        balance_after = Decimal(0)
    return Split(
        payment_number=payment_number,
        principal=principal,
        interest=interest,
        escrow=escrow,
        total=(principal + interest + escrow).quantize(_CENT),
        balance_after=balance_after,
    )


def _present_value(payment: Decimal, monthly: Decimal, term: int) -> Decimal:
    """Return the present value of an annuity.

    Args:
        payment: The payment per period.
        monthly: The per-period interest rate.
        term: The number of periods.

    Returns:
        The present value.
    """
    if monthly == 0:
        return payment * term
    factor = (Decimal(1) + monthly) ** term
    return payment * (factor - Decimal(1)) / (monthly * factor)


def ledger_balances(  # noqa: C901 - one pass over the ledger
    entries: Iterable[Directive], accounts: Iterable[str]
) -> dict[str, tuple[Decimal, date]]:
    """Compute the balance and most recent cleared date of several accounts.

    Cleared (``*``) and pending (``P``) transactions are counted; forecast
    (``#``) and placeholder (``!``) entries are ignored so the engine never
    counts its own predictions. A liability balance is credit-normal, so it is
    negated to the positive amount still owed. The accounts are gathered in one
    pass, so several amortized schedules do not each rescan the ledger.

    Args:
        entries: The ledger entries.
        accounts: The liability accounts to track.

    Returns:
        A mapping from account to its ``(balance, date)`` pair, omitting the
        accounts with no cleared postings.
    """
    wanted = set(accounts)
    if not wanted:
        return {}
    balances: dict[str, Decimal | None] = dict.fromkeys(wanted)
    latest: dict[str, date | None] = dict.fromkeys(wanted)
    earliest: date | None = None
    for entry in entries:
        if not isinstance(entry, Transaction) or entry.flag not in ("*", "P"):
            continue
        if earliest is None or entry.date < earliest:
            earliest = entry.date
        for posting in entry.postings:
            if posting.account not in wanted:
                continue
            number = _amount_number(posting.units)
            if number is not None:
                current = balances[posting.account]
                balances[posting.account] = (
                    number if current is None else current + number
                )
            seen = latest[posting.account]
            if entry.flag == "*" and (seen is None or entry.date > seen):
                latest[posting.account] = entry.date
    result: dict[str, tuple[Decimal, date]] = {}
    for account in wanted:
        balance = balances[account]
        observed = latest[account] or earliest
        if balance is None or balance == 0 or observed is None:
            continue
        result[account] = (-balance, observed)
    return result


def ledger_balance(
    entries: Iterable[Directive], account: str
) -> tuple[Decimal, date] | None:
    """Return a liability account's balance and most recent cleared date.

    A single-account wrapper over :func:`ledger_balances`.

    Args:
        entries: The ledger entries.
        account: The liability account.

    Returns:
        The ``(balance, date)`` pair, or ``None`` when the account is untracked.
    """
    return ledger_balances(entries, (account,)).get(account)


def amortized_accounts(result: ScheduleResult) -> set[str]:
    """Return the liability accounts a result's schedules amortize from.

    Args:
        result: The computed schedule result.

    Returns:
        The set of ``principal-account`` names, for a :func:`ledger_balances`
        index.
    """
    accounts: set[str] = set()
    for rule in result.rules:
        amort = rule.amortization
        if amort is not None and amort.principal_account:
            accounts.add(amort.principal_account)
    return accounts


def walk_balance(
    rule: Rule,
    balance: Decimal,
    balance_date: date,
    dates: Sequence[date],
    escrow: Decimal = Decimal(0),
) -> dict[date, Split]:
    """Walk forward from a ledger balance, splitting each payment.

    Used by balance-from-ledger amortization. Interest accrues monthly; the
    principal is what remains of the payment after interest, and the walk stops
    once the loan is repaid.

    Args:
        rule: The rule; its ``match_amount`` is the payment.
        balance: The remaining principal.
        balance_date: The date the balance was observed.
        dates: The payment dates to split, ascending.
        escrow: An extra escrow amount added on top of each payment.

    Returns:
        A mapping from payment date to :class:`Split`, omitting dates past payoff.
    """
    if rule.match_amount is None or rule.amortization is None:
        return {}
    payment = abs(rule.match_amount)
    monthly = _monthly_rate(rule.amortization.rate)
    running = balance
    splits: dict[date, Split] = {}
    for when in sorted(day for day in dates if day > balance_date):
        if running <= 0:
            break
        interest = (running * monthly).quantize(_CENT)
        principal = payment - interest
        if principal >= running:
            principal = running
            total = (principal + interest + escrow).quantize(_CENT)
            running = Decimal(0)
        else:
            total = (payment + escrow).quantize(_CENT)
            running = (running - principal).quantize(_CENT)
        splits[when] = Split(
            payment_number=0,
            principal=principal.quantize(_CENT),
            interest=interest,
            escrow=escrow,
            total=total,
            balance_after=running,
        )
    return splits


def amortization_splits(
    rule: Rule,
    nominals: Sequence[date],
    entries: Sequence[Directive] = (),
    *,
    balances: Mapping[str, tuple[Decimal, date]] | None = None,
) -> dict[date, Split]:
    """Compute the amortization split for each of a rule's occurrences.

    Args:
        rule: The rule, which must carry an ``amortization`` configuration.
        nominals: The nominal dates, ascending. They need not be contiguous, so
            a subset of a rule's occurrences works.
        entries: The ledger entries, for balance-from-ledger when ``balances``
            is not given.
        balances: A precomputed liability-balance index, so several amortized
            rules do not each rescan the ledger.

    Returns:
        A mapping from nominal date to :class:`Split`, possibly empty.
    """
    amort = rule.amortization
    if amort is None:
        return {}
    escrow = amort.escrow or Decimal(0)
    if amort.method == "static":
        # Enumerate the whole series once and take each occurrence's position,
        # rather than re-deriving it per date.
        wanted = set(nominals)
        if not wanted:
            return {}
        splits: dict[date, Split] = {}
        for index, nominal in enumerate(
            rule.nominal_dates(until=max(nominals)), start=1
        ):
            if nominal not in wanted:
                continue
            split = static_split(rule, index, escrow)
            if split is not None:
                splits[nominal] = split
        return splits
    principal = amort.principal_account
    if principal is None:
        return {}
    if balances is not None:
        observed = balances.get(principal)
    else:
        observed = ledger_balance(entries, principal)
    if observed is None:
        return {}
    balance, balance_date = observed
    return walk_balance(rule, balance, balance_date, nominals, escrow)


# --- Parsing -------------------------------------------------------------------


def _as_decimal(value: object) -> Decimal | None:
    """Coerce a value to :class:`~decimal.Decimal`.

    Args:
        value: A metadata value.

    Returns:
        The decimal, or ``None`` when it is not numeric.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, Amount):
        return value.number
    return None


def _as_int(value: object) -> int | None:
    """Coerce a value to :class:`int`.

    Args:
        value: A metadata value.

    Returns:
        The integer, or ``None`` when it is not integral.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    number = _as_decimal(value)
    if number is not None and number == number.to_integral_value():
        return int(number)
    return None


def _as_date(value: object) -> date | None:
    """Coerce a value to :class:`~datetime.date`.

    Args:
        value: A metadata value.

    Returns:
        The date, or ``None``.
    """
    return value if isinstance(value, date) else None


def _as_str(value: object) -> str | None:
    """Coerce a value to :class:`str`.

    Args:
        value: A metadata value.

    Returns:
        The string, or ``None``.
    """
    return value if isinstance(value, str) and value else None


def _window(meta: Mapping[str, object], key: str) -> int:
    """Read a match-window bound, defaulting when it is absent.

    Args:
        meta: The directive's metadata.
        key: ``"window-before"`` or ``"window-after"``.

    Returns:
        The bound, defaulting to :data:`DEFAULT_WINDOW`.
    """
    value = _as_int(meta.get(key))
    return DEFAULT_WINDOW if value is None else value


def _custom_directives(entries: Sequence[Directive]) -> list[Custom]:
    """Collect every ``custom "schedule"`` directive, in order.

    Args:
        entries: The ledger entries.

    Returns:
        The directives, sorted by date (stable for equal dates).
    """
    found = [
        entry for entry in entries if isinstance(entry, Custom) and entry.type == TYPE
    ]
    found.sort(key=lambda entry: entry.date)
    return found


def _verb_values(
    entry: Custom, diagnostics: list[Diagnostic]
) -> tuple[str, tuple[object, ...]]:
    """Return a custom directive's verb and remaining positional values.

    Args:
        entry: The directive.
        diagnostics: The list to append diagnostics to.

    Returns:
        The verb and the values that follow it, unwrapped.
    """
    values = tuple(_unwrap(value) for value in entry.values)
    verb = values[0] if values else None
    if not isinstance(verb, str) or not verb:
        diagnostics.append(_diag("E001", entry=entry, id="<unknown>", key="verb"))
        return "", ()
    return verb, values[1:]


def _parse_amortization(
    meta: Mapping[str, object],
    schedule_id: str,
    entry: Directive,
    diagnostics: list[Diagnostic],
) -> Amortization | None:
    """Parse a rule's amortization configuration, if any.

    Args:
        meta: The directive's metadata.
        schedule_id: The schedule id, for diagnostics.
        entry: The source directive.
        diagnostics: The list to append diagnostics to.

    Returns:
        The :class:`Amortization`, or ``None`` when the rule is not amortized.
    """
    flag = meta.get("balance-from-ledger")
    method = _as_str(meta.get("method"))
    if method is None and flag is True:
        method = "balance-from-ledger"
    rate = _as_decimal(meta.get("rate"))
    if method is None and rate is None:
        return None
    if method is None:
        method = "balance-from-ledger" if flag is True else "static"
    if method == "balance-from-ledger":
        principal = _as_str(meta.get("principal-account"))
        if principal is None:
            diagnostics.append(
                _diag("E001", entry=entry, id=schedule_id, key="principal-account")
            )
            return None
    elif method != "static":
        diagnostics.append(_diag("E006", entry=entry, id=schedule_id, mode=method))
        return None
    elif _as_int(meta.get("term")) is None:
        diagnostics.append(_diag("E001", entry=entry, id=schedule_id, key="term"))
        return None
    if rate is None:
        diagnostics.append(_diag("E001", entry=entry, id=schedule_id, key="rate"))
        return None
    return Amortization(
        method=method,
        rate=rate,
        term=_as_int(meta.get("term")),
        escrow=_as_decimal(meta.get("escrow")),
        principal_account=_as_str(meta.get("principal-account")),
        interest_account=_as_str(meta.get("interest-account")),
        escrow_account=_as_str(meta.get("escrow-account")),
    )


def _amount_mode(
    meta: Mapping[str, object],
    schedule_id: str,
    entry: Directive,
    diagnostics: list[Diagnostic],
) -> str:
    """Resolve a rule's amount mode, defaulting sensibly.

    Args:
        meta: The directive's metadata.
        schedule_id: The schedule id, for diagnostics.
        entry: The source directive.
        diagnostics: The list to append diagnostics to.

    Returns:
        The amount mode.
    """
    mode = _as_str(meta.get("amount-mode"))
    if mode is None:
        return "any" if meta.get("match-amount") is None else "exact"
    if mode not in AMOUNT_MODES:
        diagnostics.append(_diag("E006", entry=entry, id=schedule_id, mode=mode))
        return "any"
    return mode


def _amounts_in_currency(
    meta: Mapping[str, object],
    schedule_id: str,
    entry: Directive,
    operating_currency: str,
    diagnostics: list[Diagnostic],
) -> bool:
    """Check a rule's amount metadata against the operating currency.

    Args:
        meta: The directive's metadata.
        schedule_id: The schedule id, for diagnostics.
        entry: The source directive.
        operating_currency: The operating currency, or ``""`` when none.
        diagnostics: The list to append diagnostics to.

    Returns:
        ``True`` when every amount is in the operating currency (or there is
        none).
    """
    if not operating_currency:
        return True
    for key in (
        "match-amount",
        "amount-tolerance",
        "amount-min",
        "amount-max",
        "escrow",
    ):
        value = meta.get(key)
        if isinstance(value, Amount) and value.currency != operating_currency:
            diagnostics.append(
                _diag(
                    "E008",
                    entry=entry,
                    id=schedule_id,
                    currency=value.currency,
                    operating_currency=operating_currency,
                )
            )
            return False
    return True


def parse_rule(  # noqa: PLR0911
    entry: Custom,
    verb: str,  # noqa: ARG001 - kept for symmetry with the other verb parsers
    values: Sequence[object],
    diagnostics: list[Diagnostic],
    operating_currency: str = "",
) -> Rule | None:
    """Parse a ``new`` directive into a rule.

    Args:
        entry: The source directive.
        verb: The verb, always ``"new"``.
        values: The positional values after the verb.
        diagnostics: The list to append diagnostics to.
        operating_currency: The operating currency, for the amount check.

    Returns:
        The :class:`Rule`, or ``None`` when required metadata is missing or
        invalid.
    """
    schedule_id = _as_str(values[0]) if values else None
    if schedule_id is None:
        diagnostics.append(_diag("E001", entry=entry, id="<unknown>", key="id"))
        return None
    meta = _meta(entry)
    if not _amounts_in_currency(
        meta, schedule_id, entry, operating_currency, diagnostics
    ):
        return None
    missing = False
    for key in ("rrule", "start", "match-account"):
        if meta.get(key) is None:
            diagnostics.append(_diag("E001", entry=entry, id=schedule_id, key=key))
            missing = True
    if missing:
        return None
    rrule_text = _as_str(meta.get("rrule"))
    if rrule_text is None:
        diagnostics.append(_diag("E001", entry=entry, id=schedule_id, key="rrule"))
        return None
    try:
        recurrence.validate(rrule_text)
    except ValueError as exc:
        diagnostics.append(_diag("E002", entry=entry, id=schedule_id, detail=str(exc)))
        return None
    start = _as_date(meta.get("start"))
    match_account = _as_str(meta.get("match-account"))
    if start is None or match_account is None:
        return None
    end = _as_date(meta.get("end"))
    if end is not None and end < start:
        diagnostics.append(
            _diag(
                "E009",
                entry=entry,
                id=schedule_id,
                start=start.isoformat(),
                end=end.isoformat(),
            )
        )
        return None
    mode = _amount_mode(meta, schedule_id, entry, diagnostics)
    return Rule(
        id=schedule_id,
        declared=entry.date,
        rrule=rrule_text,
        start=start,
        end=end,
        match_account=match_account,
        match_payee=_as_str(meta.get("match-payee")),
        match_amount=_as_decimal(meta.get("match-amount")),
        amount_mode=mode,
        amount_tolerance=_as_decimal(meta.get("amount-tolerance")),
        amount_min=_as_decimal(meta.get("amount-min")),
        amount_max=_as_decimal(meta.get("amount-max")),
        window_before=_window(meta, "window-before"),
        window_after=_window(meta, "window-after"),
        payee=_as_str(meta.get("payee")),
        narration=_as_str(meta.get("narration")),
        amortization=_parse_amortization(meta, schedule_id, entry, diagnostics),
        entry=entry,
    )


# --- Resolution ----------------------------------------------------------------


def _scan_outcomes(
    directives: Sequence[Custom],
    rules: Mapping[str, Rule],
    diagnostics: list[Diagnostic],
) -> dict[tuple[str, date], Occurrence]:
    """Build the skip and move outcomes from the custom directives.

    Args:
        directives: The ``custom "schedule"`` directives.
        rules: The parsed rules, keyed by id.
        diagnostics: The list to append diagnostics to.

    Returns:
        A mapping from ``(rule_id, nominal)`` to the resolving occurrence.
    """
    outcomes: dict[tuple[str, date], Occurrence] = {}
    for entry in directives:
        verb, values = _verb_values(entry, diagnostics)
        if verb not in ("skip", "move"):
            continue
        schedule_id = _as_str(values[0]) if values else None
        if schedule_id is None:
            continue
        rule = rules.get(schedule_id)
        if rule is None:
            diagnostics.append(_diag("E004", entry=entry, id=schedule_id, verb=verb))
            continue
        nominal = entry.date
        if not _in_series(rule, nominal):
            diagnostics.append(
                _diag(
                    "W002",
                    entry=entry,
                    id=schedule_id,
                    verb=verb,
                    date=nominal.isoformat(),
                )
            )
            continue
        if not recurrence.on_sequence(rule.rrule, rule.start, nominal):
            diagnostics.append(
                _diag(
                    "E005",
                    entry=entry,
                    id=schedule_id,
                    verb=verb,
                    date=nominal.isoformat(),
                )
            )
            continue
        key = (schedule_id, nominal)
        if verb == "move":
            moved_to = _as_date(values[1]) if len(values) > 1 else None
            if moved_to is None:
                continue
            outcomes[key] = Occurrence(
                rule_id=schedule_id, nominal=nominal, moved_to=moved_to, entry=entry
            )
        else:
            outcomes[key] = Occurrence(
                rule_id=schedule_id, nominal=nominal, skipped=True, entry=entry
            )
    return outcomes


def _in_series(rule: Rule, when: date) -> bool:
    """Report whether a date falls within a rule's ``start``/``end`` window.

    Args:
        rule: The rule.
        when: The date.

    Returns:
        ``True`` when the date is in the window.
    """
    return rule.start <= when and (rule.end is None or when <= rule.end)


def _scan_postings(
    directives: Sequence[Custom],
    rules: Mapping[str, Rule],
    operating_currency: str,
    diagnostics: list[Diagnostic],
) -> dict[str, list[PostingSpec]]:
    """Collect every ``posting`` directive, keyed by schedule.

    A posting that names no known schedule is orphaned and reported (``E010``);
    one that posts to its rule's matched account is reported (``E013``).

    Args:
        directives: The ``custom "schedule"`` directives.
        rules: The parsed rules, keyed by id.
        operating_currency: The operating currency, for the amount check.
        diagnostics: The list to append diagnostics to.

    Returns:
        The postings for each schedule, in declaration order.
    """
    found: dict[str, list[PostingSpec]] = {}
    for entry in directives:
        verb, values = _verb_values(entry, diagnostics)
        if verb != "posting":
            continue
        schedule_id = _as_str(values[0]) if values else None
        account = _as_str(values[1]) if len(values) > 1 else None
        if schedule_id is None:
            diagnostics.append(_diag("E010", entry=entry, id=schedule_id))
            continue
        rule = rules.get(schedule_id)
        if rule is None:
            diagnostics.append(_diag("E010", entry=entry, id=schedule_id))
            continue
        if account is None:
            diagnostics.append(
                _diag("E001", entry=entry, id=schedule_id, key="account")
            )
            continue
        if account == rule.match_account:
            diagnostics.append(
                _diag("E013", entry=entry, id=schedule_id, account=account)
            )
            continue
        meta = _meta(entry)
        raw = meta.get("amount")
        if (
            operating_currency
            and isinstance(raw, Amount)
            and raw.currency != operating_currency
        ):
            diagnostics.append(
                _diag(
                    "E008",
                    entry=entry,
                    id=schedule_id,
                    currency=raw.currency,
                    operating_currency=operating_currency,
                )
            )
            continue
        found.setdefault(schedule_id, []).append(
            PostingSpec(
                account=account,
                amount=_as_decimal(raw),
                metadata=tuple(
                    (key, value) for key, value in meta.items() if key != "amount"
                ),
                entry=entry,
            )
        )
    return found


def _apply_postings(
    rule: Rule,
    postings: Sequence[PostingSpec],
    operating_currency: str,
    diagnostics: list[Diagnostic],
) -> Rule:
    """Attach a rule's postings and validate the split.

    Args:
        rule: The rule.
        postings: Its declared postings, in order.
        operating_currency: The operating currency, for the message.
        diagnostics: The list to append diagnostics to.

    Returns:
        The rule with its postings attached.
    """
    if not postings:
        return rule
    if rule.amortization is not None:
        diagnostics.append(_diag("E012", entry=rule.entry, id=rule.id))
        return rule
    missing = sum(1 for posting in postings if posting.amount is None)
    if missing > 1:
        diagnostics.append(_diag("E014", entry=rule.entry, id=rule.id))
    if rule.match_amount is not None and missing == 0:
        total = sum(
            (posting.amount for posting in postings if posting.amount is not None),
            Decimal(0),
        )
        expected = -rule.match_amount
        if total != expected:
            diagnostics.append(
                _diag(
                    "E011",
                    entry=rule.entry,
                    id=rule.id,
                    total=format_amount(total, operating_currency),
                    expected=format_amount(expected, operating_currency),
                )
            )
    return replace(rule, postings=tuple(postings))


def _posted_occurrences(
    entries: Sequence[Directive],
    rules: Mapping[str, Rule],
    nominals_by_rule: Mapping[str, Sequence[date]],
) -> dict[tuple[str, date], Transaction]:
    """Index the transactions that name a schedule by their nominal date.

    Each transaction's nominal date is re-derived from the rule's precomputed
    nominal list by a bisect, so the scan is linear in the entries.

    Args:
        entries: The ledger entries.
        rules: The parsed rules, keyed by id.
        nominals_by_rule: Each rule's nominal dates, ascending.

    Returns:
        A mapping from ``(rule_id, nominal)`` to the transaction.
    """
    found: dict[tuple[str, date], Transaction] = {}
    for entry in entries:
        if not isinstance(entry, Transaction):
            continue
        schedule_id = _schedule_id(entry)
        if schedule_id is None:
            continue
        rule = rules.get(schedule_id)
        if rule is None:
            continue
        nominal = _nearest_in(nominals_by_rule.get(schedule_id, ()), entry.date, rule)
        if nominal is None:
            continue
        found.setdefault((schedule_id, nominal), entry)
    return found


# --- Entry point ---------------------------------------------------------------


def _operating_currency(options: Mapping[str, object]) -> str:
    """Read the single operating currency from the ledger options.

    Args:
        options: The Beancount options map.

    Returns:
        The operating currency, or ``""`` when it is missing or ambiguous.
    """
    value = options.get("operating_currency")
    if isinstance(value, str):
        return value
    if isinstance(value, list | tuple) and len(value) == 1:
        return str(value[0])
    return ""


def _window_until(today: date | None) -> date:
    """Return the horizon a series is expanded to.

    The horizon is a fixed span from the reference date — the shell's ``today``,
    or the wall clock when none was given. It is deliberately *not* derived from
    the ledger's latest directive: a far-future ``open`` or ``custom`` would
    otherwise expand every rule across millennia and make the scan quadratic in
    years.

    Args:
        today: The reference date, if any.

    Returns:
        The horizon date.
    """
    reference = today or date.today()  # noqa: DTZ011 - fallback reference only
    return _shift(reference, _HORIZON.days)


def _build_occurrences(
    rule: Rule,
    outcomes: Mapping[tuple[str, date], Occurrence],
    posted: Mapping[tuple[str, date], Transaction],
    nominals: Sequence[date],
) -> tuple[Occurrence, ...]:
    """Build a rule's occurrences over the window, resolving each.

    Args:
        rule: The rule.
        outcomes: The skip and move outcomes.
        posted: The posted occurrences.
        nominals: The rule's nominal dates, ascending.

    Returns:
        The occurrences, ascending.
    """
    built: list[Occurrence] = []
    for nominal in nominals:
        key = (rule.id, nominal)
        transaction = posted.get(key)
        if transaction is not None:
            built.append(
                Occurrence(rule_id=rule.id, nominal=nominal, posted=transaction)
            )
            continue
        outcome = outcomes.get(key)
        if outcome is not None:
            built.append(replace(outcome, rule_id=rule.id, nominal=nominal))
            continue
        built.append(Occurrence(rule_id=rule.id, nominal=nominal))
    return tuple(built)


def compute(
    entries: Sequence[Directive],
    options: Mapping[str, object],
    *,
    today: date | None = None,
) -> ScheduleResult:
    """Compute every schedule's occurrences and diagnostics.

    Args:
        entries: The ledger entries.
        options: The Beancount options map, used for ``operating_currency``.
        today: The reference date for ``next``, overdue and the occurrence
            horizon, if any. When it is ``None`` the diagnostics that need a
            reference date are skipped and the horizon is measured from the wall
            clock; it is never measured from the ledger's last date, which a
            far-future directive would explode.

    Returns:
        The :class:`ScheduleResult`, including every diagnostic.

    Examples:
        >>> from beancount.parser import parser
        >>> ledger = '''
        ... 2026-01-01 custom "schedule" "new" "paycheck"
        ...   rrule: "FREQ=MONTHLY;BYMONTHDAY=15"
        ...   start: 2026-01-15
        ...   match-account: "Assets:Bank"
        ... '''
        >>> entries, _errors, options = parser.parse_string(ledger)
        >>> result = compute(entries, options, today=date(2026, 2, 1))
        >>> [report.id for report in result.reports]
        ['paycheck']
        >>> result.report("paycheck").next
        datetime.date(2026, 1, 15)
        >>> result.report("paycheck").overdue
        (datetime.date(2026, 1, 15),)
    """
    diagnostics: list[Diagnostic] = []
    entries = list(entries)
    directives = _custom_directives(entries)
    currency = _operating_currency(options)

    rules: dict[str, Rule] = {}
    order: list[Rule] = []
    for entry in directives:
        verb, values = _verb_values(entry, diagnostics)
        if verb != "new":
            continue
        rule = parse_rule(entry, verb, values, diagnostics, currency)
        if rule is None:
            continue
        if rule.id in rules:
            diagnostics.append(_diag("E003", entry=entry, id=rule.id))
            continue
        rules[rule.id] = rule
        order.append(rule)

    declared = _scan_postings(directives, rules, currency, diagnostics)
    order = [
        _apply_postings(rule, declared.get(rule.id, []), currency, diagnostics)
        for rule in order
    ]
    rules = {rule.id: rule for rule in order}

    outcomes = _scan_outcomes(directives, rules, diagnostics)
    until = _window_until(today)
    nominals = {rule.id: tuple(rule.nominal_dates(until=until)) for rule in order}
    posted = _posted_occurrences(entries, rules, nominals)

    reports: list[ScheduleReport] = []
    for rule in order:
        occurrences = _build_occurrences(rule, outcomes, posted, nominals[rule.id])
        reports.append(
            ScheduleReport(
                rule=rule,
                occurrences=occurrences,
                next=_next_unresolved(occurrences),
                overdue=_overdue(occurrences, today),
            )
        )
    if today is not None:
        _warn_overdue(reports, diagnostics)

    return ScheduleResult(
        rules=tuple(order),
        reports=tuple(reports),
        diagnostics=tuple(_sorted(diagnostics)),
    )


def _next_unresolved(occurrences: Sequence[Occurrence]) -> date | None:
    """Return the first nominal date with no resolved occurrence.

    Args:
        occurrences: The occurrences, ascending.

    Returns:
        The earliest unresolved nominal date, or ``None``.
    """
    for occurrence in occurrences:
        if not occurrence.resolved:
            return occurrence.nominal
    return None


def _overdue(occurrences: Sequence[Occurrence], today: date | None) -> tuple[date, ...]:
    """Return the unresolved nominal dates strictly before the reference date.

    Args:
        occurrences: The occurrences, ascending.
        today: The reference date, if any.

    Returns:
        The overdue nominal dates.
    """
    if today is None:
        return ()
    return tuple(
        occurrence.nominal
        for occurrence in occurrences
        if not occurrence.resolved and occurrence.nominal < today
    )


def _warn_overdue(
    reports: Sequence[ScheduleReport], diagnostics: list[Diagnostic]
) -> None:
    """Warn about each schedule with unresolved occurrences past due.

    Args:
        reports: The schedule reports.
        diagnostics: The list to append diagnostics to.
    """
    for report in reports:
        if not report.overdue:
            continue
        diagnostics.append(
            _diag(
                "W001",
                entry=report.rule.entry,
                id=report.id,
                count=len(report.overdue),
                date=report.overdue[0].isoformat(),
            )
        )
