"""Forecast transaction advancement logic."""

import logging
from datetime import date, timedelta
from typing import Optional

from beancount.core import data

from .recurrence import RecurrenceEngine
from .schema import Schedule

logger = logging.getLogger(__name__)


def calculate_next_occurrence(schedule: Schedule, after_date: date) -> Optional[date]:
    """
    Calculate the next occurrence date for a schedule after a given date.

    Ignores the schedule's start_date and only uses the recurrence pattern
    to find the next occurrence after the given date.

    Args:
        schedule: Schedule to calculate next occurrence for
        after_date: Calculate next occurrence after this date

    Returns:
        Next occurrence date, or None if no more occurrences

    Example:
        >>> schedule = Schedule(...)  # MONTHLY on 1st
        >>> calculate_next_occurrence(schedule, date(2024, 1, 3))
        date(2024, 2, 1)
    """
    from copy import copy

    engine = RecurrenceEngine()

    # Create a modified schedule with start_date set to after_date
    # This ensures we generate occurrences starting from after_date,
    # not from the forecast transaction's current date
    modified_schedule = copy(schedule)
    modified_recurrence = copy(schedule.recurrence)

    # Set start_date to after_date to avoid skipping forward
    # This makes the engine generate from after_date regardless of
    # what the forecast file currently says
    modified_recurrence.start_date = after_date
    modified_schedule.recurrence = modified_recurrence

    # Use a reasonable end date (1 year from after_date)
    end_date = after_date + timedelta(days=365)

    # If schedule has end_date and it's before our window, use it
    if schedule.recurrence.end_date and schedule.recurrence.end_date < end_date:
        end_date = schedule.recurrence.end_date

    # Generate occurrences from after_date
    occurrences = engine.generate(modified_schedule, after_date, end_date)

    # Filter to dates after after_date
    future_occurrences = [d for d in occurrences if d > after_date]

    if not future_occurrences:
        logger.warning(
            "No future occurrences found for schedule %s after %s",
            schedule.id,
            after_date,
        )
        return None

    next_date = future_occurrences[0]
    logger.debug(
        "Calculated next occurrence for %s: %s -> %s",
        schedule.id,
        after_date,
        next_date,
    )

    return next_date


def advance_forecast_transaction(
    forecast_txn: data.Transaction,
    next_date: date,
) -> data.Transaction:
    """
    Create a new forecast transaction with advanced date.

    Args:
        forecast_txn: Original forecast transaction
        next_date: New date to advance to

    Returns:
        New Transaction with updated date, same metadata/postings

    Example:
        >>> original = data.Transaction(..., date=date(2024, 1, 1), ...)
        >>> updated = advance_forecast_transaction(original, date(2024, 2, 1))
        >>> updated.date
        date(2024, 2, 1)
    """
    # Create new transaction with updated date
    new_txn = forecast_txn._replace(date=next_date)

    logger.debug(
        "Advanced forecast transaction %s: %s -> %s",
        forecast_txn.meta.get("schedule-id"),
        forecast_txn.date,
        next_date,
    )

    return new_txn
