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
            dtstart = datetime.combine(effective_start, datetime.min.time())
            until = datetime.combine(effective_end, datetime.max.time())
            rule = rrulestr(recurrence.rrule, dtstart=dtstart, ignoretz=True)
            return sorted({d.date() for d in rule.between(dtstart, until, inc=True)})
        except Exception as e:
            logger.error(
                "Error generating recurrence for schedule %s: %s", schedule.id, e
            )
            return []
