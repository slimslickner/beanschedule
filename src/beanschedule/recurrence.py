"""Recurrence rule engine for generating expected transaction dates."""

import logging
from datetime import date, datetime
from typing import List

from dateutil.rrule import MONTHLY, WEEKLY, YEARLY, rrule

from .schema import RecurrenceRule, Schedule
from .types import WEEKDAY_MAP, FrequencyType

logger = logging.getLogger(__name__)


class RecurrenceEngine:
    """Engine for generating expected dates from recurrence rules."""

    def generate(self, schedule: Schedule, start_date: date, end_date: date) -> List[date]:
        """
        Generate expected dates for schedule within date range.

        Args:
            schedule: Schedule definition with recurrence rule
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of expected occurrence dates within range
        """
        recurrence = schedule.recurrence

        # Determine effective start/end dates
        effective_start = max(recurrence.start_date, start_date)
        if recurrence.end_date:
            effective_end = min(recurrence.end_date, end_date)
        else:
            effective_end = end_date

        # If range is invalid, return empty
        if effective_start > effective_end:
            return []

        try:
            if recurrence.frequency == FrequencyType.MONTHLY:
                return self._generate_monthly(recurrence, effective_start, effective_end)
            if recurrence.frequency == FrequencyType.WEEKLY:
                return self._generate_weekly(recurrence, effective_start, effective_end)
            if recurrence.frequency == FrequencyType.YEARLY:
                return self._generate_yearly(recurrence, effective_start, effective_end)
            if recurrence.frequency == FrequencyType.INTERVAL:
                return self._generate_interval(recurrence, effective_start, effective_end)
            if recurrence.frequency == FrequencyType.BIMONTHLY:
                return self._generate_bimonthly(recurrence, effective_start, effective_end)
            logger.error(f"Unknown frequency type: {recurrence.frequency}")
            return []
        except Exception as e:
            logger.error(f"Error generating recurrence for schedule {schedule.id}: {e}")
            return []

    def _generate_monthly(
        self,
        recurrence: RecurrenceRule,
        start_date: date,
        end_date: date,
    ) -> List[date]:
        """Generate monthly recurrence dates."""
        if recurrence.day_of_month is None:
            logger.error("MONTHLY frequency requires day_of_month")
            return []

        dates = list(
            rrule(
                MONTHLY,
                dtstart=datetime.combine(start_date, datetime.min.time()),
                until=datetime.combine(end_date, datetime.max.time()),
                bymonthday=recurrence.day_of_month,
            ),
        )

        return [d.date() for d in dates]

    def _generate_weekly(
        self,
        recurrence: RecurrenceRule,
        start_date: date,
        end_date: date,
    ) -> List[date]:
        """Generate weekly recurrence dates."""
        if recurrence.day_of_week is None:
            logger.error("WEEKLY frequency requires day_of_week")
            return []

        interval = recurrence.interval or 1
        weekday = WEEKDAY_MAP[recurrence.day_of_week]

        dates = list(
            rrule(
                WEEKLY,
                interval=interval,
                dtstart=datetime.combine(start_date, datetime.min.time()),
                until=datetime.combine(end_date, datetime.max.time()),
                byweekday=weekday,
            ),
        )

        return [d.date() for d in dates]

    def _generate_yearly(
        self,
        recurrence: RecurrenceRule,
        start_date: date,
        end_date: date,
    ) -> List[date]:
        """Generate yearly recurrence dates."""
        if recurrence.month is None or recurrence.day_of_month is None:
            logger.error("YEARLY frequency requires month and day_of_month")
            return []

        dates = list(
            rrule(
                YEARLY,
                dtstart=datetime.combine(start_date, datetime.min.time()),
                until=datetime.combine(end_date, datetime.max.time()),
                bymonth=recurrence.month,
                bymonthday=recurrence.day_of_month,
            ),
        )

        return [d.date() for d in dates]

    def _generate_interval(
        self,
        recurrence: RecurrenceRule,
        start_date: date,
        end_date: date,
    ) -> List[date]:
        """Generate interval-based recurrence dates (every X months)."""
        if recurrence.interval_months is None or recurrence.day_of_month is None:
            logger.error("INTERVAL frequency requires interval_months and day_of_month")
            return []

        dates = list(
            rrule(
                MONTHLY,
                interval=recurrence.interval_months,
                dtstart=datetime.combine(start_date, datetime.min.time()),
                until=datetime.combine(end_date, datetime.max.time()),
                bymonthday=recurrence.day_of_month,
            ),
        )

        return [d.date() for d in dates]

    def _generate_bimonthly(
        self,
        recurrence: RecurrenceRule,
        start_date: date,
        end_date: date,
    ) -> List[date]:
        """Generate bi-monthly recurrence dates (multiple days per month)."""
        if recurrence.days_of_month is None or len(recurrence.days_of_month) == 0:
            logger.error("BIMONTHLY frequency requires days_of_month")
            return []

        all_dates = []
        for day in recurrence.days_of_month:
            dates = list(
                rrule(
                    MONTHLY,
                    dtstart=datetime.combine(start_date, datetime.min.time()),
                    until=datetime.combine(end_date, datetime.max.time()),
                    bymonthday=day,
                ),
            )
            all_dates.extend([d.date() for d in dates])

        # Sort and remove duplicates
        return sorted(set(all_dates))
