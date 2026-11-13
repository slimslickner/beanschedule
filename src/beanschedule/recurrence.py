"""Pure RRULE date generation.

The recurrence rule is the authoritative source of a schedule's nominal dates.
This module wraps :mod:`dateutil.rrule` so the rest of the engine works in
``datetime.date`` terms only, and so the rule's phase comes from the schedule's
``start`` date rather than from any ``DTSTART`` embedded in the rule text.

A rule is stored without a ``DTSTART`` part; the anchor is supplied separately.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from dateutil.rrule import rrule, rrulestr

__all__ = [
    "at_or_before",
    "between",
    "next_after",
    "occurrences",
    "on_sequence",
    "parse",
    "sequence_index",
    "validate",
]

#: The latest date a query will expand toward when no bound is given.
_FOREVER = date.max


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
