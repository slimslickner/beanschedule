"""Recurrence rule engine for generating expected transaction dates."""

import logging
from datetime import date, datetime

from dateutil.rrule import rrulestr

from .schema import Schedule

logger = logging.getLogger(__name__)


class RecurrenceEngine:
    """Engine for generating expected dates from recurrence rules."""

    def generate(
        self, schedule: Schedule, start_date: date, end_date: date
    ) -> list[date]:
        """Generate expected dates for schedule within date range."""
        recurrence = schedule.recurrence
        effective_start = max(recurrence.start_date, start_date)
        effective_end = (
            min(recurrence.end_date, end_date) if recurrence.end_date else end_date
        )
        if effective_start > effective_end:
            return []

        try:
            # Anchor dtstart to recurrence.start_date so interval-based rules
            # (FREQ=WEEKLY;INTERVAL=2, FREQ=MONTHLY;INTERVAL=4, etc.) generate a
            # consistent date sequence regardless of which query window is used.
            # between() then filters to the effective_start/effective_end window.
            dtstart = datetime.combine(recurrence.start_date, datetime.min.time())
            after = datetime.combine(effective_start, datetime.min.time())
            until = datetime.combine(effective_end, datetime.max.time())
            rule = rrulestr(recurrence.rrule, dtstart=dtstart, ignoretz=True)
            return sorted({d.date() for d in rule.between(after, until, inc=True)})
        except Exception as e:
            logger.error(
                "Error generating recurrence for schedule %s: %s", schedule.id, e
            )
            return []
