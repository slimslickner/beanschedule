"""Recurrence rule engine for generating expected transaction dates."""

import logging
from datetime import date, datetime

from dateutil.rrule import MONTHLY, WEEKLY, YEARLY, rrule
from dateutil.rrule import MO, TU, WE, TH, FR, SA, SU

from . import constants
from .schema import RecurrenceRule, Schedule
from .types import WEEKDAY_MAP, FrequencyType

logger = logging.getLogger(__name__)


class RecurrenceEngine:
    """Engine for generating expected dates from recurrence rules."""

    def generate(self, schedule: Schedule, start_date: date, end_date: date) -> list[date]:
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
        effective_end = min(recurrence.end_date, end_date) if recurrence.end_date else end_date

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
            if recurrence.frequency == FrequencyType.MONTHLY_ON_DAYS:
                return self._generate_monthly_on_days(recurrence, effective_start, effective_end)
            if recurrence.frequency == FrequencyType.NTH_WEEKDAY:
                return self._generate_nth_weekday(recurrence, effective_start, effective_end)
            if recurrence.frequency == FrequencyType.LAST_DAY_OF_MONTH:
                return self._generate_last_day_of_month(recurrence, effective_start, effective_end)
            logger.error("Unknown frequency type: %s", recurrence.frequency)
            return []
        except Exception as e:
            logger.error("Error generating recurrence for schedule %s: %s", schedule.id, e)
            return []

    def _generate_monthly(
        self,
        recurrence: RecurrenceRule,
        start_date: date,
        end_date: date,
    ) -> list[date]:
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
    ) -> list[date]:
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
    ) -> list[date]:
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
    ) -> list[date]:
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
    ) -> list[date]:
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

    def _generate_monthly_on_days(
        self,
        recurrence: RecurrenceRule,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        """
        Generate recurrence on multiple specific days of each month.

        Example: 5th and 20th of each month for paychecks.

        Args:
            recurrence: Recurrence rule with days_of_month
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of dates on specified days of each month
        """
        if recurrence.days_of_month is None or len(recurrence.days_of_month) == 0:
            logger.error("MONTHLY_ON_DAYS frequency requires days_of_month")
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

    def _generate_nth_weekday(
        self,
        recurrence: RecurrenceRule,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        """
        Generate recurrence on Nth occurrence of a weekday in each month.

        Examples:
            - 2nd Tuesday of each month
            - Last Friday of each month (nth_occurrence = -1)

        Args:
            recurrence: Recurrence rule with nth_occurrence and day_of_week
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of dates on Nth weekday of each month
        """
        if recurrence.nth_occurrence is None or recurrence.day_of_week is None:
            logger.error("NTH_WEEKDAY frequency requires nth_occurrence and day_of_week")
            return []

        weekday = WEEKDAY_MAP[recurrence.day_of_week]

        # Use byweekday with nth occurrence
        # dateutil.rrule uses +1 for "first", +2 for "second", etc.
        # and -1 for "last"
        weekday_objects = [MO, TU, WE, TH, FR, SA, SU]
        weekday_obj = weekday_objects[weekday]

        # Apply nth occurrence
        if recurrence.nth_occurrence == -1:
            # Last occurrence
            weekday_with_nth = weekday_obj(-1)
        else:
            # Nth occurrence (1-based)
            weekday_with_nth = weekday_obj(recurrence.nth_occurrence)

        dates = list(
            rrule(
                MONTHLY,
                dtstart=datetime.combine(start_date, datetime.min.time()),
                until=datetime.combine(end_date, datetime.max.time()),
                byweekday=weekday_with_nth,
            ),
        )

        return [d.date() for d in dates]

    def _generate_last_day_of_month(
        self,
        _recurrence: RecurrenceRule,  # Not used but required for signature consistency
        start_date: date,
        end_date: date,
    ) -> list[date]:
        """
        Generate recurrence on the last day of each month.

        Handles months with different numbers of days (28-31).

        Args:
            recurrence: Recurrence rule
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of dates on last day of each month
        """
        # Use dateutil's bymonthday=-1 for last day
        dates = list(
            rrule(
                MONTHLY,
                dtstart=datetime.combine(start_date, datetime.min.time()),
                until=datetime.combine(end_date, datetime.max.time()),
                bymonthday=constants.LAST_DAY_OF_MONTH_INDICATOR,  # Last day of month
            ),
        )

        return [d.date() for d in dates]
