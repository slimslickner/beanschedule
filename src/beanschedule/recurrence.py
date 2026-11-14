"""Pure RRULE date generation.

The recurrence rule is the authoritative source of a schedule's nominal dates.
This module wraps :mod:`dateutil.rrule` so the rest of the engine works in
``datetime.date`` terms only, and so the rule's phase comes from the schedule's
``start`` date rather than from any ``DTSTART`` embedded in the rule text.

A rule is stored without a ``DTSTART`` part; the anchor is supplied separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from dateutil.rrule import rrule, rrulestr

__all__ = [
    "RuleFields",
    "at_or_before",
    "between",
    "build_rrule",
    "next_after",
    "occurrences",
    "on_sequence",
    "parse",
    "rrule_fields",
    "sequence_index",
    "validate",
]

#: The latest date a query will expand toward when no bound is given.
_FOREVER = date.max

#: The weekday tokens RFC 5545 uses in ``BYDAY``, in calendar order.
WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


@dataclass(frozen=True, slots=True)
class RuleFields:
    """The structured parts of a recurrence rule, for a UI form.

    A rule is built from these parts by :func:`build_rrule` and decomposed back
    into them by :func:`rrule_fields`, so a form can round-trip what the ledger
    holds without the user ever typing rule text.

    Attributes:
        freq: The ``FREQ`` part, e.g. ``"MONTHLY"``.
        interval: The ``INTERVAL`` part, defaulting to ``1``.
        byday: The weekday tokens of ``BYDAY``, e.g. ``("MO", "FR")``.
        bymonthday: The day-of-month of ``BYMONTHDAY``, if any.
        bymonth: The month of ``BYMONTH``, if any.
    """

    freq: str
    interval: int = 1
    byday: tuple[str, ...] = ()
    bymonthday: int | None = None
    bymonth: int | None = None


def build_rrule(
    freq: str,
    *,
    interval: int = 1,
    byday: tuple[str, ...] | list[str] = (),
    bymonthday: int | None = None,
    bymonth: int | None = None,
) -> str:
    """Compose an RFC 5545 recurrence rule from its parts.

    Only the parts a schedule UI offers are emitted, and the result is validated
    against the same parser the engine uses, so a form cannot submit a rule the
    engine would later reject.

    Args:
        freq: The frequency, e.g. ``"MONTHLY"``.
        interval: How many intervals between occurrences; ``1`` is every one.
        byday: Weekday tokens for ``BYDAY``, e.g. ``("MO", "FR")``.
        bymonthday: A day of the month for ``BYMONTHDAY``, if any.
        bymonth: A month for ``BYMONTH``, if any.

    Returns:
        The recurrence rule, without a ``DTSTART``.

    Raises:
        ValueError: If the composed rule is not a valid recurrence.

    Examples:
        >>> build_rrule("MONTHLY", bymonthday=15)
        'FREQ=MONTHLY;BYMONTHDAY=15'
        >>> build_rrule("WEEKLY", interval=2, byday=["MO", "FR"])
        'FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR'
    """
    parts = [f"FREQ={freq.strip().upper()}"]
    if interval and interval != 1:
        parts.append(f"INTERVAL={int(interval)}")
    days = tuple(day.strip().upper() for day in byday if day and day.strip())
    if days:
        parts.append("BYDAY=" + ",".join(days))
    if bymonthday:
        parts.append(f"BYMONTHDAY={int(bymonthday)}")
    if bymonth:
        parts.append(f"BYMONTH={int(bymonth)}")
    text = ";".join(parts)
    validate(text)
    return text


def rrule_fields(text: str) -> RuleFields:
    """Decompose a recurrence rule into its structured parts.

    Parsing is best-effort and never raises: an unknown or malformed part is
    simply omitted, so a form can prefill from any rule the ledger holds.

    Args:
        text: The recurrence rule, without a ``DTSTART``.

    Returns:
        The :class:`RuleFields`, defaulting the frequency to ``""``.

    Examples:
        >>> rrule_fields("FREQ=MONTHLY;BYMONTHDAY=15")
        RuleFields(freq='MONTHLY', interval=1, byday=(), bymonthday=15, bymonth=None)
        >>> rrule_fields("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR")
        RuleFields(freq='WEEKLY', interval=2, byday=('MO', 'FR'), bymonthday=None, bymonth=None)
    """
    parts: dict[str, str] = {}
    for chunk in text.split(";"):
        key, sep, value = chunk.partition("=")
        if sep:
            parts[key.strip().upper()] = value.strip()
    byday = tuple(
        day
        for day in (
            token.strip().upper() for token in parts.get("BYDAY", "").split(",")
        )
        if day
    )
    return RuleFields(
        freq=parts.get("FREQ", "").upper(),
        interval=_as_int(parts.get("INTERVAL")) or 1,
        byday=byday,
        bymonthday=_as_int(parts.get("BYMONTHDAY")),
        bymonth=_as_int(parts.get("BYMONTH")),
    )


def _as_int(value: str | None) -> int | None:
    """Parse an optional integer part, ignoring anything unparseable.

    Args:
        value: The raw part, or ``None``.

    Returns:
        The integer, or ``None``.

    Examples:
        >>> _as_int("15")
        15
        >>> _as_int(None) is None
        True
        >>> _as_int("x") is None
        True
    """
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse(rrule_text: str, start: date) -> rrule:
    """Parse an RRULE string and anchor it to a start date.

    Args:
        rrule_text: The RFC 5545 recurrence rule, without a ``DTSTART``.
        start: The date the series begins, which sets the interval phase.

    Returns:
        The parsed rule, anchored at ``start``.

    Raises:
        ValueError: If the text is not a valid recurrence rule.

    Examples:
        >>> parse("FREQ=MONTHLY;BYMONTHDAY=15", date(2026, 1, 15)).after(
        ...     datetime(2026, 1, 1)
        ... )
        datetime.datetime(2026, 1, 15, 0, 0)
    """
    anchor = datetime.combine(start, time.min)
    try:
        parsed = rrulestr(rrule_text, dtstart=anchor, ignoretz=True)
    except (ValueError, TypeError) as exc:  # dateutil raises a mix of types
        message = f"invalid rrule: {exc}"
        raise ValueError(message) from exc
    if not isinstance(parsed, rrule):
        message = "rrule text must describe a single recurrence, not a rule set"
        raise ValueError(message)  # noqa: TRY004 - callers catch ValueError uniformly
    return parsed


def validate(rrule_text: str) -> None:
    """Check that an RRULE string parses, without keeping the result.

    Args:
        rrule_text: The RFC 5545 recurrence rule.

    Raises:
        ValueError: If the text is not a valid recurrence rule.
    """
    parse(rrule_text, date(2000, 1, 1))


def occurrences(
    rrule_text: str,
    start: date,
    *,
    after: date | None = None,
    until: date | None = None,
    end: date | None = None,
    limit: int | None = None,
) -> list[date]:
    """List a rule's nominal dates within a window.

    Args:
        rrule_text: The RFC 5545 recurrence rule, without a ``DTSTART``.
        start: The date the series begins, anchoring the interval phase.
        after: The earliest date to include, inclusive; defaults to ``start``.
        until: The latest date to include, inclusive; defaults to unbounded.
        end: The series' own last date, inclusive, when it has one.
        limit: A maximum number of dates to return.

    Returns:
        The nominal dates, ascending.

    Examples:
        >>> [d.isoformat() for d in occurrences(
        ...     "FREQ=MONTHLY;BYMONTHDAY=15", date(2026, 1, 15),
        ...     until=date(2026, 4, 15),
        ... )]
        ['2026-01-15', '2026-02-15', '2026-03-15', '2026-04-15']
    """
    rule = parse(rrule_text, start)
    low = max(start, after) if after is not None else start
    if end is not None and (until is None or end < until):
        until = end
    high = until if until is not None else _FOREVER
    if low > high:
        return []
    found = [
        moment.date()
        for moment in rule.between(
            datetime.combine(low, time.min),
            datetime.combine(high, time.max),
            inc=True,
        )
    ]
    return found if limit is None else found[:limit]


def between(rrule_text: str, start: date, after: date, until: date) -> list[date]:
    """List a rule's nominal dates in a closed window.

    Args:
        rrule_text: The RFC 5545 recurrence rule, without a ``DTSTART``.
        start: The date the series begins.
        after: The earliest date to include, inclusive.
        until: The latest date to include, inclusive.

    Returns:
        The nominal dates, ascending.

    Examples:
        >>> [d.isoformat() for d in between(
        ...     "FREQ=WEEKLY;BYDAY=FR", date(2026, 1, 2),
        ...     date(2026, 1, 1), date(2026, 1, 31),
        ... )]
        ['2026-01-02', '2026-01-09', '2026-01-16', '2026-01-23', '2026-01-30']
    """
    return occurrences(rrule_text, start, after=after, until=until)


def at_or_before(rrule_text: str, start: date, when: date) -> date | None:
    """Return the latest nominal date on or before a date.

    Args:
        rrule_text: The RFC 5545 recurrence rule, without a ``DTSTART``.
        start: The date the series begins.
        when: The reference date.

    Returns:
        The latest nominal date at or before ``when``, or ``None`` when the
        series has not begun by then.

    Examples:
        >>> at_or_before("FREQ=MONTHLY;BYMONTHDAY=15", date(2026, 1, 15), date(2026, 3, 1))
        datetime.date(2026, 2, 15)
    """
    if when < start:
        return None
    found = occurrences(rrule_text, start, after=start, until=when, limit=None)
    return found[-1] if found else None


def next_after(
    rrule_text: str, start: date, when: date, *, end: date | None = None
) -> date | None:
    """Return the first nominal date strictly after a date.

    Args:
        rrule_text: The RFC 5545 recurrence rule, without a ``DTSTART``.
        start: The date the series begins.
        when: The reference date.
        end: The series' own last date, inclusive, when it has one.

    Returns:
        The next nominal date after ``when``, or ``None`` when the series has
        ended.

    Examples:
        >>> next_after("FREQ=MONTHLY;BYMONTHDAY=15", date(2026, 1, 15), date(2026, 1, 15))
        datetime.date(2026, 2, 15)
        >>> next_after(
        ...     "FREQ=MONTHLY;BYMONTHDAY=15", date(2026, 1, 15),
        ...     date(2026, 1, 15), end=date(2026, 1, 31),
        ... ) is None
        True
    """
    rule = parse(rrule_text, start)
    moment = rule.after(datetime.combine(when, time.min), inc=False)
    if moment is None:
        return None
    found = moment.date()
    if end is not None and found > end:
        return None
    return found


def on_sequence(rrule_text: str, start: date, when: date) -> bool:
    """Report whether a date is one the rule generates.

    Args:
        rrule_text: The RFC 5545 recurrence rule, without a ``DTSTART``.
        start: The date the series begins.
        when: The date to check.

    Returns:
        ``True`` when ``when`` is a nominal date.

    Examples:
        >>> on_sequence("FREQ=MONTHLY;BYMONTHDAY=15", date(2026, 1, 15), date(2026, 2, 15))
        True
        >>> on_sequence("FREQ=MONTHLY;BYMONTHDAY=15", date(2026, 1, 15), date(2026, 2, 16))
        False
    """
    return bool(between(rrule_text, start, when, when))


def sequence_index(rrule_text: str, start: date, when: date) -> int | None:
    """Return a nominal date's one-based position in the series.

    Args:
        rrule_text: The RFC 5545 recurrence rule, without a ``DTSTART``.
        start: The date the series begins.
        when: The nominal date.

    Returns:
        The one-based index, or ``None`` when ``when`` is not on the sequence.

    Examples:
        >>> sequence_index("FREQ=MONTHLY;BYMONTHDAY=15", date(2026, 1, 15), date(2026, 3, 15))
        3
    """
    if not on_sequence(rrule_text, start, when):
        return None
    return len(occurrences(rrule_text, start, after=start, until=when))


def _shift_days(value: date, days: int) -> date:
    """Shift a date by a signed number of days.

    Args:
        value: The date to shift.
        days: The number of days.

    Returns:
        The shifted date.
    """
    return value + timedelta(days=days)
