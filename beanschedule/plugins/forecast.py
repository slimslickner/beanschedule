"""Extended forecast plugin for Beancount with advanced recurrence patterns.

Forked from beanlabs forecast plugin with support for beanschedule's
extended recurrence patterns.

This plugin supports both narration-based patterns (beanlabs-compatible)
and metadata-based schedules (beanschedule format).

Basic Usage (beanlabs-compatible):

    2024-01-01 # "Rent Payment" "Monthly rent [MONTHLY]"
      Expenses:Housing:Rent     1500.00 USD
      Assets:Checking          -1500.00 USD

Extended Patterns (beanschedule):

    2024-01-05 # "Paycheck" "Semi-monthly pay [MONTHLY ON 5,20]"
      schedule-id: "paycheck"
      schedule-frequency: "MONTHLY_ON_DAYS"
      schedule-days-of-month: "5,20"
      Assets:Checking           2500.00 USD
      Income:Salary            -2500.00 USD

    2024-01-09 # "Team Meeting" "Monthly sync [2ND TUE]"
      schedule-id: "meeting"
      schedule-frequency: "NTH_WEEKDAY"
      schedule-nth-occurrence: "2"
      schedule-day-of-week: "TUE"
      Expenses:Dining:Team      50.00 USD
      Assets:Checking          -50.00 USD

Supported Patterns:
- [MONTHLY], [WEEKLY], [YEARLY], [DAILY] - beanlabs compatible
- [MONTHLY ON 5,20] - multiple days per month
- [2ND TUE], [LAST FRI] - nth weekday of month
- [LAST DAY OF MONTH] - variable month lengths
- [EVERY 3 MONTHS] - interval-based
- [MONTHLY UNTIL 2024-12-31] - with end date
"""

__copyright__ = "Copyright (C) 2014-2017  Martin Blais (original), 2026 beanschedule (fork)"
__license__ = "GNU GPLv2"

import datetime
import logging
import re
from datetime import date
from typing import Optional

from dateutil import rrule
from dateutil.rrule import MO, TU, WE, TH, FR, SA, SU

from beancount.core import data

logger = logging.getLogger(__name__)

__plugins__ = ('forecast',)


# Map day of week strings to dateutil weekday constants
WEEKDAY_MAP = {
    'MON': 0,
    'TUE': 1,
    'WED': 2,
    'THU': 3,
    'FRI': 4,
    'SAT': 5,
    'SUN': 6,
}

WEEKDAY_OBJECTS = [MO, TU, WE, TH, FR, SA, SU]


def parse_pattern_from_narration(narration: str) -> Optional[dict]:
    """
    Parse forecast pattern from transaction narration.

    Args:
        narration: Transaction narration string

    Returns:
        Dict with pattern info or None if no pattern found
    """
    # Pattern: [...] in narration
    pattern_match = re.search(r'\[([^\]]+)\]', narration)
    if not pattern_match:
        return None

    pattern_str = pattern_match.group(1)
    result = {
        'base_narration': narration[:pattern_match.start()].strip(),
        'interval': rrule.MONTHLY,  # default
        'periodicity': {},
    }

    # Parse UNTIL condition
    until_match = re.search(r'UNTIL\s+(\d{4}-\d{2}-\d{2})', pattern_str)
    if until_match:
        result['periodicity']['until'] = datetime.datetime.strptime(
            until_match.group(1), '%Y-%m-%d'
        ).date()
        pattern_str = pattern_str[:until_match.start()].strip()

    # Parse REPEAT condition
    repeat_match = re.search(r'REPEAT\s+(\d+)\s+TIME', pattern_str)
    if repeat_match:
        result['periodicity']['count'] = int(repeat_match.group(1))
        pattern_str = pattern_str[:repeat_match.start()].strip()

    # Parse SKIP condition
    skip_match = re.search(r'SKIP\s+(\d+)\s+TIME', pattern_str)
    if skip_match:
        result['periodicity']['interval'] = int(skip_match.group(1)) + 1
        pattern_str = pattern_str[:skip_match.start()].strip()

    # Parse frequency patterns
    if re.match(r'MONTHLY ON\s+[\d,]+', pattern_str):
        # Extended: [MONTHLY ON 5,20]
        result['pattern_type'] = 'MONTHLY_ON_DAYS'
        days_match = re.search(r'ON\s+([\d,]+)', pattern_str)
        if days_match:
            result['days_of_month'] = [int(d.strip()) for d in days_match.group(1).split(',')]

    elif re.match(r'(1ST|2ND|3RD|\dTH|LAST)\s+(MON|TUE|WED|THU|FRI|SAT|SUN)', pattern_str):
        # Extended: [2ND TUE], [LAST FRI]
        result['pattern_type'] = 'NTH_WEEKDAY'
        nth_match = re.match(
            r'(1ST|2ND|3RD|(\d)TH|LAST)\s+(MON|TUE|WED|THU|FRI|SAT|SUN)', pattern_str
        )
        if nth_match:
            nth_str = nth_match.group(1)
            if nth_str == 'LAST':
                result['nth_occurrence'] = -1
            elif nth_str == '1ST':
                result['nth_occurrence'] = 1
            elif nth_str == '2ND':
                result['nth_occurrence'] = 2
            elif nth_str == '3RD':
                result['nth_occurrence'] = 3
            else:
                result['nth_occurrence'] = int(nth_match.group(2))

            day_str = nth_match.group(3)
            result['day_of_week'] = WEEKDAY_MAP[day_str]

    elif 'LAST DAY OF MONTH' in pattern_str:
        # Extended: [LAST DAY OF MONTH]
        result['pattern_type'] = 'LAST_DAY_OF_MONTH'

    elif re.match(r'EVERY\s+(\d+)\s+MONTHS', pattern_str):
        # Extended: [EVERY 3 MONTHS]
        result['pattern_type'] = 'INTERVAL'
        interval_match = re.search(r'EVERY\s+(\d+)\s+MONTHS', pattern_str)
        if interval_match:
            result['periodicity']['interval'] = int(interval_match.group(1))

    elif 'YEARLY' in pattern_str:
        result['pattern_type'] = 'YEARLY'
        result['interval'] = rrule.YEARLY

    elif 'WEEKLY' in pattern_str:
        result['pattern_type'] = 'WEEKLY'
        result['interval'] = rrule.WEEKLY

    elif 'DAILY' in pattern_str:
        result['pattern_type'] = 'DAILY'
        result['interval'] = rrule.DAILY

    elif 'MONTHLY' in pattern_str:
        result['pattern_type'] = 'MONTHLY'
        result['interval'] = rrule.MONTHLY

    else:
        # Unknown pattern
        return None

    return result


def parse_pattern_from_metadata(entry: data.Transaction) -> Optional[dict]:
    """
    Parse forecast pattern from transaction metadata.

    Args:
        entry: Transaction with schedule-* metadata

    Returns:
        Dict with pattern info or None if no metadata found
    """
    if not hasattr(entry, 'meta') or not entry.meta:
        return None

    frequency = entry.meta.get('schedule-frequency')
    if not frequency:
        return None

    result = {
        'base_narration': entry.narration,
        'interval': rrule.MONTHLY,
        'periodicity': {},
        'pattern_type': frequency,
    }

    # Parse end date
    until_str = entry.meta.get('schedule-until')
    if until_str:
        try:
            result['periodicity']['until'] = date.fromisoformat(until_str)
        except ValueError:
            pass

    # Parse pattern-specific fields
    if frequency in ('MONTHLY_ON_DAYS', 'BIMONTHLY'):
        days_str = entry.meta.get('schedule-days-of-month')
        if days_str:
            result['days_of_month'] = [int(d.strip()) for d in days_str.split(',')]

    elif frequency == 'NTH_WEEKDAY':
        nth_str = entry.meta.get('schedule-nth-occurrence')
        day_str = entry.meta.get('schedule-day-of-week')
        if nth_str and day_str:
            result['nth_occurrence'] = int(nth_str)
            result['day_of_week'] = WEEKDAY_MAP.get(day_str, 0)

    elif frequency == 'INTERVAL':
        interval_str = entry.meta.get('schedule-interval-months')
        if interval_str:
            result['periodicity']['interval'] = int(interval_str)

    elif frequency == 'WEEKLY':
        interval_str = entry.meta.get('schedule-interval')
        if interval_str:
            result['periodicity']['interval'] = int(interval_str)
        result['interval'] = rrule.WEEKLY

    elif frequency == 'YEARLY':
        result['interval'] = rrule.YEARLY

    elif frequency == 'DAILY':
        result['interval'] = rrule.DAILY

    return result


def generate_forecast_dates(entry: data.Transaction, pattern: dict) -> list[date]:
    """
    Generate forecast dates based on parsed pattern.

    Args:
        entry: Original forecast transaction
        pattern: Parsed pattern dictionary

    Returns:
        List of forecast dates
    """
    pattern_type = pattern.get('pattern_type', 'MONTHLY')
    periodicity = pattern['periodicity'].copy()
    periodicity['dtstart'] = entry.date

    # Set default end date if not specified
    if 'until' not in periodicity and 'count' not in periodicity:
        periodicity['until'] = date(date.today().year, 12, 31)

    try:
        if pattern_type == 'MONTHLY_ON_DAYS':
            # Generate on multiple days per month
            all_dates = []
            for day in pattern.get('days_of_month', []):
                dates = [
                    dt.date()
                    for dt in rrule.rrule(rrule.MONTHLY, bymonthday=day, **periodicity)
                ]
                all_dates.extend(dates)
            return sorted(set(all_dates))

        elif pattern_type == 'NTH_WEEKDAY':
            # Generate nth weekday of each month
            nth = pattern.get('nth_occurrence', 1)
            weekday_idx = pattern.get('day_of_week', 0)
            weekday_obj = WEEKDAY_OBJECTS[weekday_idx]

            if nth == -1:
                weekday_with_nth = weekday_obj(-1)
            else:
                weekday_with_nth = weekday_obj(nth)

            dates = [
                dt.date()
                for dt in rrule.rrule(rrule.MONTHLY, byweekday=weekday_with_nth, **periodicity)
            ]
            return dates

        elif pattern_type == 'LAST_DAY_OF_MONTH':
            # Generate last day of each month
            dates = [
                dt.date()
                for dt in rrule.rrule(rrule.MONTHLY, bymonthday=-1, **periodicity)
            ]
            return dates

        else:
            # Standard patterns: MONTHLY, WEEKLY, YEARLY, DAILY
            interval = pattern.get('interval', rrule.MONTHLY)
            dates = [dt.date() for dt in rrule.rrule(interval, **periodicity)]
            return dates

    except Exception as e:
        logger.warning("Failed to generate forecast dates for %s: %s", entry, e)
        return []


def forecast(entries, options_map):
    """
    Extended forecast plugin with support for advanced recurrence patterns.

    This plugin is compatible with beanlabs forecast plugin for basic patterns
    (MONTHLY, WEEKLY, YEARLY, DAILY) and extends it to support:
    - MONTHLY ON 5,20 (multiple days per month)
    - 2ND TUE, LAST FRI (nth weekday patterns)
    - LAST DAY OF MONTH (variable month lengths)
    - EVERY 3 MONTHS (interval-based)

    Args:
      entries: List of beancount entries
      options_map: Options map from beancount

    Returns:
      Tuple of (filtered_entries + new_entries, errors)
    """
    # Filter out forecast entries
    forecast_entries = []
    filtered_entries = []

    for entry in entries:
        if isinstance(entry, data.Transaction) and entry.flag == '#':
            forecast_entries.append(entry)
        else:
            filtered_entries.append(entry)

    # Generate forecast entries
    new_entries = []

    for entry in forecast_entries:
        # Try parsing from metadata first, then narration
        pattern = parse_pattern_from_metadata(entry) or parse_pattern_from_narration(
            entry.narration
        )

        if not pattern:
            # No valid pattern found, keep original
            new_entries.append(entry)
            continue

        # Generate forecast dates
        forecast_dates = generate_forecast_dates(entry, pattern)

        # Create new entries for each date
        base_narration = pattern.get('base_narration', entry.narration)
        for forecast_date in forecast_dates:
            # Preserve required metadata fields
            new_meta = entry.meta.copy() if entry.meta else {}
            if 'lineno' not in new_meta:
                new_meta['lineno'] = 0
            if 'filename' not in new_meta:
                new_meta['filename'] = ''

            forecast_entry = entry._replace(
                meta=new_meta, date=forecast_date, narration=base_narration
            )
            new_entries.append(forecast_entry)

    # Sort and return
    new_entries.sort(key=data.entry_sortkey)

    return (filtered_entries + new_entries, [])
