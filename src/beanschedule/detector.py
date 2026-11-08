"""Recurring-transaction pattern detection.

Reads a ledger and proposes ``custom "schedule" "new"`` directives for the
recurring payments it finds. The proposal is only a suggestion: the CLI's
``detect`` prints the directives and ``create`` writes them, and neither guesses
on the user's behalf.

The detector groups transactions by account, payee and amount, measures the gaps
between them, maps the median gap to an RRULE, and scores the result. It is
pure: it reads entries and returns proposals, and never writes.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from beancount.core import data

from beanschedule import actions
from beanschedule.core import PostingSpec

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from beancount.core.data import Custom, Directive, Transaction

    from beanschedule.core import ScheduleResult

__all__ = [
    "DEFAULT_AMOUNT_TOLERANCE_PCT",
    "DEFAULT_FUZZY_THRESHOLD",
    "DEFAULT_MIN_CONFIDENCE",
    "DEFAULT_MIN_OCCURRENCES",
    "GapAnalysis",
    "Proposal",
    "TransactionGroup",
    "detect",
]

DEFAULT_FUZZY_THRESHOLD = 0.85
DEFAULT_AMOUNT_TOLERANCE_PCT = 0.05
DEFAULT_MIN_OCCURRENCES = 3
DEFAULT_MIN_CONFIDENCE = 0.60

#: The day ranges each frequency is recognised within.
_WEEKLY = (6, 8)
_BIWEEKLY = (12, 16)
_MONTHLY = (25, 35)
_QUARTERLY = (85, 95)
_YEARLY = (355, 375)

_WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")

_COVERAGE_WEIGHT = 0.5
_REGULARITY_WEIGHT = 0.3
_SAMPLE_WEIGHT = 0.2
_SAMPLE_INTERCEPT = 0.7
_SAMPLE_DENOMINATOR = 15.0

#: The fewest dates needed to measure a gap.
_MIN_SAMPLES = 2
#: The longest generated schedule id before it is truncated to the slug.
_MAX_ID_LENGTH = 50


@dataclass(frozen=True, slots=True)
class TransactionGroup:
    """A group of similar transactions.

    Attributes:
        account: The matched account.
        payee: The canonical payee.
        postings: The other-side ``(account, amount)`` pairs seen in the group.
        amounts: The absolute amounts.
        transactions: The transactions, oldest first.
        dates: Their dates, oldest first.
    """

    account: str
    payee: str
    postings: tuple[tuple[str, Decimal], ...]
    amounts: tuple[Decimal, ...]
    transactions: tuple[Transaction, ...]
    dates: tuple[date, ...]

    @property
    def accounts(self) -> tuple[str, ...]:
        """The other-side posting accounts."""
        return tuple(account for account, _amount in self.postings)

    @property
    def count(self) -> int:
        """The number of transactions in the group."""
        return len(self.transactions)


@dataclass(frozen=True, slots=True)
class GapAnalysis:
    """The gaps between a group's transactions.

    Attributes:
        gaps: The gaps in days.
        median: The median gap.
        mean: The mean gap.
        std_dev: The standard deviation of the gaps.
    """

    gaps: tuple[int, ...] = ()
    median: int = 0
    mean: float = 0.0
    std_dev: float = 0.0

    @property
    def regularity(self) -> float:
        """The regularity score, penalising a variable gap.

        Returns:
            ``1 - std_dev / mean``, clamped to ``0`` to ``1``.
        """
        if self.mean == 0:
            return 0.0
        return max(0.0, 1.0 - self.std_dev / self.mean)


@dataclass(frozen=True, slots=True)
class Proposal:
    """A proposed schedule.

    Attributes:
        schedule_id: The suggested id.
        account: The matched account.
        accounts: The other-side accounts.
        postings: The proposed other-side postings, with amounts.
        rrule: The suggested recurrence rule.
        start: The first nominal date.
        payee: The canonical payee.
        amount: The typical amount, with the sign of the matched posting.
        amount_tolerance: The ± tolerance.
        confidence: The confidence, from ``0`` to ``1``.
        count: The number of supporting transactions.
        first_date: The earliest supporting date.
        last_date: The latest supporting date.
    """

    schedule_id: str
    account: str
    accounts: tuple[str, ...]
    postings: tuple[PostingSpec, ...]
    rrule: str
    start: date
    payee: str
    amount: Decimal
    amount_tolerance: Decimal
    confidence: float
    count: int
    first_date: date
    last_date: date

    def directives(self) -> list[Custom]:
        """Render the proposal as a ``new`` directive and its postings.

        Returns:
            The directives, the ``new`` first.
        """
        return [
            actions.new(
                self.schedule_id,
                self.start,
                rrule=self.rrule,
                start=self.start,
                match_account=self.account,
                match_payee=self.payee,
                match_amount=self.amount,
                amount_mode="approx",
                amount_tolerance=self.amount_tolerance,
                payee=self.payee,
            ),
            *(
                actions.posting(
                    self.schedule_id,
                    spec.account,
                    self.start,
                    amount=spec.amount,
                )
                for spec in self.postings
            ),
        ]


def detect(
    entries: Sequence[Directive],
    *,
    exclude: ScheduleResult | None = None,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
    amount_tolerance_pct: float = DEFAULT_AMOUNT_TOLERANCE_PCT,
    min_occurrences: int = DEFAULT_MIN_OCCURRENCES,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> list[Proposal]:
    """Detect recurring patterns and propose schedules for them.

    Args:
        entries: The ledger entries.
        exclude: A computed result whose schedules' accounts are already
            covered, so their transactions are not proposed again.
        fuzzy_threshold: The payee fuzzy-match threshold.
        amount_tolerance_pct: The amount variance tolerance, as a fraction.
        min_occurrences: The minimum supporting transactions.
        min_confidence: The minimum confidence to include.

    Returns:
        The proposals, most confident first.
    """
    transactions = [
        entry
        for entry in entries
        if isinstance(entry, data.Transaction) and entry.postings and entry.payee
    ]
    covered = (
        {rule.match_account for rule in exclude.rules} if exclude is not None else set()
    )
    groups = _group(
        transactions,
        fuzzy_threshold=fuzzy_threshold,
        amount_tolerance_pct=amount_tolerance_pct,
        covered=covered,
    )
    proposals: list[Proposal] = []
    for group in groups:
        if group.count < min_occurrences:
            continue
        gaps = _analyze_gaps(group)
        rrule_text = _rrule(gaps, group)
        if rrule_text is None:
            continue
        confidence = _confidence(group, gaps)
        if confidence < min_confidence:
            continue
        proposals.append(_proposal(group, rrule_text, confidence, amount_tolerance_pct))
    proposals.sort(key=lambda proposal: proposal.confidence, reverse=True)
    return proposals


# --- Grouping ------------------------------------------------------------------


def _group(
    transactions: Sequence[Transaction],
    *,
    fuzzy_threshold: float,
    amount_tolerance_pct: float,
    covered: set[str],
) -> list[TransactionGroup]:
    """Group transactions by account, payee and amount.

    Args:
        transactions: The transactions to group.
        fuzzy_threshold: The payee fuzzy-match threshold.
        amount_tolerance_pct: The amount variance tolerance.
        covered: Accounts already covered by a schedule, skipped.

    Returns:
        The groups.
    """
    by_account: dict[str, list[Transaction]] = defaultdict(list)
    for txn in transactions:
        account = txn.postings[0].account
        if account not in covered:
            by_account[account].append(txn)

    groups: list[TransactionGroup] = []
    for account, in_account in by_account.items():
        for payee_group in _payee_groups(in_account, fuzzy_threshold):
            groups.extend(
                _make_group(account, amount_group)
                for amount_group in _amount_groups(payee_group, amount_tolerance_pct)
            )
    return groups


def _payee_groups(
    transactions: Sequence[Transaction], threshold: float
) -> list[list[Transaction]]:
    """Split transactions into fuzzy-payee groups.

    Args:
        transactions: The transactions.
        threshold: The fuzzy-match threshold.

    Returns:
        The groups.
    """
    groups: list[list[Transaction]] = []
    for txn in transactions:
        placed = False
        for group in groups:
            canonical = group[0].payee
            if txn.payee and canonical and _fuzzy(txn.payee, canonical) >= threshold:
                group.append(txn)
                placed = True
                break
        if not placed:
            groups.append([txn])
    return groups


def _amount_groups(
    transactions: Sequence[Transaction], tolerance_pct: float
) -> list[list[Transaction]]:
    """Split transactions into amount-tolerance groups.

    Args:
        transactions: The transactions.
        tolerance_pct: The amount variance tolerance.

    Returns:
        The groups.
    """
    groups: list[list[Transaction]] = []
    for txn in transactions:
        units = txn.postings[0].units
        if units is None or units.number is None:
            continue
        amount = abs(units.number)
        placed = False
        for group in groups:
            reference = group[0].postings[0].units
            if reference is None or reference.number is None:
                continue
            reference_amount = abs(reference.number)
            tolerance = reference_amount * Decimal(str(tolerance_pct))
            if reference_amount - tolerance <= amount <= reference_amount + tolerance:
                group.append(txn)
                placed = True
                break
        if not placed:
            groups.append([txn])
    return groups


def _make_group(account: str, transactions: Sequence[Transaction]) -> TransactionGroup:
    """Build a group from its transactions.

    Args:
        account: The matched account.
        transactions: The transactions.

    Returns:
        The group.
    """
    ordered = sorted(transactions, key=lambda txn: txn.date)
    payees = [txn.payee for txn in ordered if txn.payee]
    payee = max(set(payees), key=payees.count) if payees else "Unknown"
    postings = tuple(
        (posting.account, posting.units.number)
        for posting in ordered[-1].postings
        if posting.account != account
        and posting.units is not None
        and posting.units.number is not None
    )
    amounts = tuple(
        abs(txn.postings[0].units.number)
        for txn in ordered
        if txn.postings[0].units is not None
        and txn.postings[0].units.number is not None
    )
    return TransactionGroup(
        account=account,
        payee=payee,
        postings=postings,
        amounts=amounts,
        transactions=tuple(ordered),
        dates=tuple(txn.date for txn in ordered),
    )


def _analyze_gaps(group: TransactionGroup) -> GapAnalysis:
    """Measure the gaps between a group's transactions.

    Args:
        group: The group.

    Returns:
        The :class:`GapAnalysis`.
    """
    if len(group.dates) < _MIN_SAMPLES:
        return GapAnalysis()
    gaps = [
        (group.dates[index] - group.dates[index - 1]).days
        for index in range(1, len(group.dates))
    ]
    gaps = [gap for gap in gaps if gap > 0]
    if not gaps:
        return GapAnalysis()
    return GapAnalysis(
        gaps=tuple(gaps),
        median=int(statistics.median(gaps)),
        mean=statistics.mean(gaps),
        std_dev=statistics.stdev(gaps) if len(gaps) > 1 else 0.0,
    )


def _rrule(gaps: GapAnalysis, group: TransactionGroup) -> str | None:  # noqa: PLR0911
    """Map a median gap to a recurrence rule.

    Args:
        gaps: The gap analysis.
        group: The group, for the day-of-month and weekday.

    Returns:
        The RRULE text, or ``None`` when no frequency fits.
    """
    median = gaps.median
    if median == 0:
        return None
    if _WEEKLY[0] <= median <= _WEEKLY[1]:
        return f"FREQ=WEEKLY;BYDAY={_weekday(group.dates)}"
    if _BIWEEKLY[0] <= median <= _BIWEEKLY[1]:
        return f"FREQ=WEEKLY;INTERVAL=2;BYDAY={_weekday(group.dates)}"
    if _MONTHLY[0] <= median <= _MONTHLY[1]:
        return f"FREQ=MONTHLY;BYMONTHDAY={_day(group.dates)}"
    if _QUARTERLY[0] <= median <= _QUARTERLY[1]:
        return f"FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY={_day(group.dates)}"
    if _YEARLY[0] <= median <= _YEARLY[1]:
        month, day = _month_day(group.dates)
        return f"FREQ=YEARLY;BYMONTH={month};BYMONTHDAY={day}"
    return None


def _confidence(group: TransactionGroup, gaps: GapAnalysis) -> float:
    """Score a group's recurring likelihood.

    Args:
        group: The group.
        gaps: The gap analysis.

    Returns:
        The confidence, from ``0`` to ``1``.
    """
    expected = _expected(gaps, group)
    coverage = min(1.0, group.count / expected) if expected else 1.0
    sample = min(1.0, _SAMPLE_INTERCEPT + group.count / _SAMPLE_DENOMINATOR)
    return (
        coverage * _COVERAGE_WEIGHT
        + gaps.regularity * _REGULARITY_WEIGHT
        + sample * _SAMPLE_WEIGHT
    )


def _expected(gaps: GapAnalysis, group: TransactionGroup) -> int:
    """Estimate how many occurrences a gap implies over the group's span.

    Args:
        gaps: The gap analysis.
        group: The group.

    Returns:
        The expected occurrence count.
    """
    if gaps.median <= 0 or len(group.dates) < _MIN_SAMPLES:
        return group.count
    span = (group.dates[-1] - group.dates[0]).days
    return max(1, span // gaps.median + 1)


def _proposal(
    group: TransactionGroup,
    rrule_text: str,
    confidence: float,
    tolerance_pct: float,
) -> Proposal:
    """Build a proposal from a group.

    Args:
        group: The group.
        rrule_text: The recurrence rule.
        confidence: The confidence score.
        tolerance_pct: The amount variance tolerance.

    Returns:
        The :class:`Proposal`.
    """
    average = (
        sum(group.amounts, Decimal(0)) / len(group.amounts)
        if group.amounts
        else Decimal(0)
    )
    signed = _signed_amount(group)
    slug = _slugify(group.payee)
    frequency = _frequency_name(rrule_text)
    schedule_id = f"{slug}-{frequency}"
    if len(schedule_id) > _MAX_ID_LENGTH:
        schedule_id = slug
    return Proposal(
        schedule_id=schedule_id,
        account=group.account,
        accounts=group.accounts,
        postings=tuple(
            PostingSpec(account, amount, ()) for account, amount in group.postings
        ),
        rrule=rrule_text,
        start=group.dates[0],
        payee=group.payee,
        amount=signed,
        amount_tolerance=average * Decimal(str(tolerance_pct)),
        confidence=confidence,
        count=group.count,
        first_date=group.dates[0],
        last_date=group.dates[-1],
    )


def _signed_amount(group: TransactionGroup) -> Decimal:
    """Return the typical signed amount of the matched posting.

    Args:
        group: The group.

    Returns:
        The most recent matched posting's amount.
    """
    last = group.transactions[-1].postings[0].units
    if last is not None and last.number is not None:
        return last.number
    return Decimal(0)


def _frequency_name(rrule_text: str) -> str:
    """Return a short slug for a recurrence rule.

    Args:
        rrule_text: The rule text.

    Returns:
        The slug, such as ``monthly`` or ``every-3-months``.
    """
    if "INTERVAL=3" in rrule_text:
        return "quarterly"
    if "INTERVAL=2" in rrule_text:
        return "biweekly"
    if rrule_text.startswith("FREQ=WEEKLY"):
        return "weekly"
    if rrule_text.startswith("FREQ=YEARLY"):
        return "yearly"
    return "monthly"


def _slugify(value: str) -> str:
    """Reduce a payee to a lowercase slug.

    Args:
        value: The payee.

    Returns:
        The slug.

    Examples:
        >>> _slugify("Edison Power & Light")
        'edison-power-light'
    """
    kept = [ch.lower() if ch.isalnum() else "-" for ch in value]
    slug = "".join(kept)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "schedule"


def _fuzzy(left: str, right: str) -> float:
    """Return the similarity of two payees.

    Args:
        left: The first payee.
        right: The second payee.

    Returns:
        The similarity, from ``0`` to ``1``.
    """
    return SequenceMatcher(None, left.upper().strip(), right.upper().strip()).ratio()


def _day(dates: Sequence[date]) -> int:
    """Return the most common day of month.

    Args:
        dates: The dates.

    Returns:
        The day, defaulting to the first.
    """
    if not dates:
        return 1
    counter = Counter(day.day for day in dates)
    month_end = sum(counter.get(day, 0) for day in (28, 29, 30, 31))
    if month_end > len(dates) // 2:
        return 28
    return max(counter, key=lambda key: counter.get(key, 0))


def _weekday(dates: Sequence[date]) -> str:
    """Return the most common weekday token.

    Args:
        dates: The dates.

    Returns:
        The two-letter weekday, such as ``FR``.
    """
    if not dates:
        return "MO"
    counter = Counter(_WEEKDAYS[day.weekday()] for day in dates)
    return max(counter, key=lambda key: counter.get(key, 0))


def _month_day(dates: Sequence[date]) -> tuple[int, int]:
    """Return the most common month and day.

    Args:
        dates: The dates.

    Returns:
        The ``(month, day)`` pair, defaulting to January 1st.
    """
    if not dates:
        return (1, 1)
    months = Counter(day.month for day in dates)
    days = Counter(day.day for day in dates)
    return (
        max(months, key=lambda key: months.get(key, 0)),
        max(days, key=lambda key: days.get(key, 0)),
    )
