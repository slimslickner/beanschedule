"""Load schedule templates from forecast transactions (# flag)."""

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Optional

from beancount.core import data

from .schema import (
    GlobalConfig,
    MatchCriteria,
    MissingTransactionConfig,
    Posting,
    RecurrenceRule,
    Schedule,
    ScheduleFile,
    TransactionTemplate,
)
from .types import DayOfWeek, FrequencyType

logger = logging.getLogger(__name__)

# Metadata field names
SCHEDULE_ID = "schedule-id"
SCHEDULE_FREQUENCY = "schedule-frequency"
SCHEDULE_INTERVAL = "schedule-interval"
SCHEDULE_INTERVAL_MONTHS = "schedule-interval-months"
SCHEDULE_DAY_OF_MONTH = "schedule-day-of-month"
SCHEDULE_MONTH = "schedule-month"
SCHEDULE_DAY_OF_WEEK = "schedule-day-of-week"
SCHEDULE_DAYS_OF_MONTH = "schedule-days-of-month"
SCHEDULE_NTH_OCCURRENCE = "schedule-nth-occurrence"
SCHEDULE_UNTIL = "schedule-until"
SCHEDULE_PAYEE_PATTERN = "schedule-payee-pattern"
SCHEDULE_MATCH_ACCOUNT = "schedule-match-account"
SCHEDULE_AMOUNT = "schedule-amount"
SCHEDULE_AMOUNT_TOLERANCE = "schedule-amount-tolerance"
SCHEDULE_AMOUNT_MIN = "schedule-amount-min"
SCHEDULE_AMOUNT_MAX = "schedule-amount-max"
SCHEDULE_DATE_WINDOW_DAYS = "schedule-date-window-days"
SCHEDULE_ENABLED = "schedule-enabled"
SCHEDULE_PLACEHOLDER_FLAG = "schedule-placeholder-flag"
SCHEDULE_PLACEHOLDER_NARRATION_PREFIX = "schedule-placeholder-narration-prefix"


def parse_narration_pattern(narration: str) -> dict:
    """
    Parse forecast pattern from transaction narration.

    Supports both beanlabs-compatible patterns and extended patterns:
    - [MONTHLY] - beanlabs compatible
    - [WEEKLY] - beanlabs compatible
    - [YEARLY] - beanlabs compatible
    - [MONTHLY ON 5,20] - extended (multiple days)
    - [2ND TUE] - extended (nth weekday)
    - [LAST FRI] - extended (last weekday)
    - [LAST DAY OF MONTH] - extended
    - [EVERY 3 MONTHS] - extended (interval)
    - [MONTHLY UNTIL 2024-12-31] - with end date

    Args:
        narration: Transaction narration string

    Returns:
        Dict with parsed pattern info: {
            'frequency': str,
            'days_of_month': list[int],
            'nth_occurrence': int,
            'day_of_week': str,
            'interval_months': int,
            'end_date': date,
        }
    """
    result = {}

    # Pattern: [...] at end of narration
    pattern_match = re.search(r'\[([^\]]+)\]', narration)
    if not pattern_match:
        return result

    pattern_str = pattern_match.group(1)

    # Parse UNTIL condition
    until_match = re.search(r'UNTIL\s+(\d{4}-\d{2}-\d{2})', pattern_str)
    if until_match:
        try:
            result['end_date'] = date.fromisoformat(until_match.group(1))
            # Remove UNTIL from pattern for further parsing
            pattern_str = pattern_str[:until_match.start()].strip()
        except ValueError:
            pass

    # Parse frequency patterns
    if re.match(r'MONTHLY ON\s+[\d,]+', pattern_str):
        # [MONTHLY ON 5,20]
        result['frequency'] = 'MONTHLY_ON_DAYS'
        days_match = re.search(r'ON\s+([\d,]+)', pattern_str)
        if days_match:
            result['days_of_month'] = [int(d.strip()) for d in days_match.group(1).split(',')]

    elif re.match(r'BIMONTHLY ON\s+[\d,]+', pattern_str):
        # [BIMONTHLY ON 5,20]
        result['frequency'] = 'BIMONTHLY'
        days_match = re.search(r'ON\s+([\d,]+)', pattern_str)
        if days_match:
            result['days_of_month'] = [int(d.strip()) for d in days_match.group(1).split(',')]

    elif re.match(r'(1ST|2ND|3RD|\dTH|LAST)\s+(MON|TUE|WED|THU|FRI|SAT|SUN)', pattern_str):
        # [2ND TUE], [LAST FRI]
        result['frequency'] = 'NTH_WEEKDAY'
        nth_match = re.match(r'(1ST|2ND|3RD|(\d)TH|LAST)\s+(MON|TUE|WED|THU|FRI|SAT|SUN)', pattern_str)
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

            result['day_of_week'] = nth_match.group(3)

    elif 'LAST DAY OF MONTH' in pattern_str:
        # [LAST DAY OF MONTH]
        result['frequency'] = 'LAST_DAY_OF_MONTH'

    elif re.match(r'EVERY\s+(\d+)\s+MONTHS', pattern_str):
        # [EVERY 3 MONTHS]
        result['frequency'] = 'INTERVAL'
        interval_match = re.search(r'EVERY\s+(\d+)\s+MONTHS', pattern_str)
        if interval_match:
            result['interval_months'] = int(interval_match.group(1))

    elif 'MONTHLY' in pattern_str:
        result['frequency'] = 'MONTHLY'

    elif 'WEEKLY' in pattern_str:
        result['frequency'] = 'WEEKLY'

    elif 'YEARLY' in pattern_str:
        result['frequency'] = 'YEARLY'

    elif 'DAILY' in pattern_str:
        result['frequency'] = 'DAILY'

    elif 'BIMONTHLY' in pattern_str:
        result['frequency'] = 'BIMONTHLY'

    return result


def is_forecast_transaction(entry: data.Directive) -> bool:
    """
    Check if entry is a forecast transaction.

    Args:
        entry: Beancount directive to check

    Returns:
        True if entry is a Transaction with # flag and schedule-id metadata
    """
    if not isinstance(entry, data.Transaction):
        return False

    if entry.flag != "#":
        return False

    return SCHEDULE_ID in entry.meta


def parse_forecast_transaction(txn: data.Transaction) -> Optional[Schedule]:
    """
    Parse a forecast transaction into a Schedule object.

    Args:
        txn: Forecast transaction (# flag with schedule-* metadata)

    Returns:
        Schedule object or None if parsing fails

    Example:
        >>> txn = data.Transaction(
        ...     meta={
        ...         'schedule-id': 'rent-monthly',
        ...         'schedule-frequency': 'MONTHLY',
        ...         'schedule-payee-pattern': '.*LANDLORD.*',
        ...         'schedule-match-account': 'Assets:Checking',
        ...     },
        ...     date=date(2024, 1, 1),
        ...     flag='#',
        ...     payee='Rent Payment',
        ...     narration='Monthly rent',
        ...     tags=frozenset(['rent']),
        ...     links=frozenset(),
        ...     postings=[...],
        ... )
        >>> schedule = parse_forecast_transaction(txn)
        >>> schedule.id
        'rent-monthly'
    """
    try:
        # Required fields
        schedule_id = txn.meta.get(SCHEDULE_ID)
        if not schedule_id:
            logger.warning("Forecast transaction missing schedule-id metadata: %s", txn)
            return None

        frequency_str = txn.meta.get(SCHEDULE_FREQUENCY)

        # If no metadata frequency, try parsing from narration
        narration_pattern = {}
        if not frequency_str and txn.narration:
            narration_pattern = parse_narration_pattern(txn.narration)
            frequency_str = narration_pattern.get('frequency')

        if not frequency_str:
            logger.warning("Forecast transaction missing schedule-frequency: %s", schedule_id)
            return None

        match_account = txn.meta.get(SCHEDULE_MATCH_ACCOUNT)
        if not match_account:
            logger.warning("Forecast transaction missing schedule-match-account: %s", schedule_id)
            return None

        # Parse frequency
        try:
            frequency = FrequencyType(frequency_str)
        except ValueError:
            logger.warning(
                "Invalid schedule-frequency '%s' for %s",
                frequency_str,
                schedule_id,
            )
            return None

        # Build MatchCriteria
        match = MatchCriteria(
            account=match_account,
            payee_pattern=txn.meta.get(SCHEDULE_PAYEE_PATTERN, ".*"),
            amount=_parse_decimal(txn.meta.get(SCHEDULE_AMOUNT)),
            amount_tolerance=_parse_decimal(txn.meta.get(SCHEDULE_AMOUNT_TOLERANCE)),
            amount_min=_parse_decimal(txn.meta.get(SCHEDULE_AMOUNT_MIN)),
            amount_max=_parse_decimal(txn.meta.get(SCHEDULE_AMOUNT_MAX)),
            date_window_days=_parse_int(txn.meta.get(SCHEDULE_DATE_WINDOW_DAYS), default=3),
        )

        # Build RecurrenceRule (use narration pattern as fallback for missing metadata)
        recurrence = RecurrenceRule(
            frequency=frequency,
            start_date=txn.date,
            end_date=(
                _parse_date(txn.meta.get(SCHEDULE_UNTIL))
                or narration_pattern.get('end_date')
            ),
            day_of_month=_parse_int(txn.meta.get(SCHEDULE_DAY_OF_MONTH)),
            month=_parse_int(txn.meta.get(SCHEDULE_MONTH)),
            day_of_week=(
                txn.meta.get(SCHEDULE_DAY_OF_WEEK)
                or narration_pattern.get('day_of_week')
            ),
            interval=_parse_int(txn.meta.get(SCHEDULE_INTERVAL), default=1),
            days_of_month=(
                _parse_int_list(txn.meta.get(SCHEDULE_DAYS_OF_MONTH))
                or narration_pattern.get('days_of_month')
            ),
            interval_months=(
                _parse_int(txn.meta.get(SCHEDULE_INTERVAL_MONTHS))
                or narration_pattern.get('interval_months')
            ),
            nth_occurrence=(
                _parse_int(txn.meta.get(SCHEDULE_NTH_OCCURRENCE))
                or narration_pattern.get('nth_occurrence')
            ),
        )

        # Build TransactionTemplate
        postings = [
            Posting(
                account=p.account,
                amount=p.units.number if p.units else None,
                narration=p.meta.get("narration") if p.meta else None,
            )
            for p in txn.postings
        ]

        # Strip forecast pattern from narration for clean display
        clean_narration = txn.narration
        if clean_narration:
            clean_narration = re.sub(r'\s*\[[^\]]+\]\s*$', '', clean_narration).strip()

        transaction = TransactionTemplate(
            payee=txn.payee,
            narration=clean_narration,
            tags=list(txn.tags) if txn.tags else [],
            metadata={"schedule_id": schedule_id},
            postings=postings,
        )

        # Build MissingTransactionConfig
        missing_transaction = MissingTransactionConfig(
            create_placeholder=True,
            flag=txn.meta.get(SCHEDULE_PLACEHOLDER_FLAG, "!"),
            narration_prefix=txn.meta.get(SCHEDULE_PLACEHOLDER_NARRATION_PREFIX, "[MISSING]"),
        )

        # Build Schedule
        schedule = Schedule(
            id=schedule_id,
            enabled=_parse_bool(txn.meta.get(SCHEDULE_ENABLED), default=True),
            match=match,
            recurrence=recurrence,
            transaction=transaction,
            missing_transaction=missing_transaction,
        )

        return schedule

    except Exception as e:
        logger.error("Failed to parse forecast transaction %s: %s", txn, e)
        return None


def load_forecast_schedules(
    existing_entries: Optional[list[data.Directive]] = None,
) -> Optional[ScheduleFile]:
    """
    Load schedules from forecast transactions in existing ledger entries.

    Args:
        existing_entries: List of beancount directives from ledger

    Returns:
        ScheduleFile with schedules parsed from forecast transactions,
        or None if no entries provided

    Example:
        >>> entries = [
        ...     # Forecast transaction
        ...     data.Transaction(..., flag='#', ...),
        ...     # Regular transaction
        ...     data.Transaction(..., flag='*', ...),
        ... ]
        >>> schedule_file = load_forecast_schedules(entries)
        >>> len(schedule_file.schedules)
        1
    """
    if existing_entries is None:
        logger.debug("No existing_entries provided")
        return None

    schedules = []
    for entry in existing_entries:
        if is_forecast_transaction(entry):
            schedule = parse_forecast_transaction(entry)
            if schedule:
                schedules.append(schedule)

    if not schedules:
        logger.info("No forecast transactions found in existing_entries")
        return None

    logger.info("Loaded %d forecast schedules from existing_entries", len(schedules))

    return ScheduleFile(
        version="2.0",  # Forecast format version
        schedules=schedules,
        config=GlobalConfig(),  # Use defaults
    )


# Helper functions


def _parse_decimal(value: Optional[str | Decimal]) -> Optional[Decimal]:
    """Parse string or Decimal to Decimal."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _parse_int(value: Optional[str | int], default: Optional[int] = None) -> Optional[int]:
    """Parse string or int to int."""
    if value is None:
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except Exception:
        return default


def _parse_int_list(value: Optional[str | list[int]]) -> Optional[list[int]]:
    """Parse comma-separated string or list to list of ints."""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return [int(x.strip()) for x in value.split(",")]
        except Exception:
            return None
    return None


def _parse_date(value: Optional[str | date]) -> Optional[date]:
    """Parse ISO date string to date."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except Exception:
        return None


def _parse_bool(value: Optional[str | bool], default: bool = True) -> bool:
    """Parse string or bool to bool."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "y")
    return default
